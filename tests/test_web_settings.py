"""Tests for R6 settings API (/api/settings*, 图形化模型配置后端).

Covers: masking on read, .env rewrite preserving unknown lines/comments,
empty-key-means-keep-existing contract, connection-test endpoint with a
faked LLM client. App construction mirrors test_web_api.py: bare FastAPI +
hand-wired ``app.state.cwd`` (no lifespan).

缺陷 G 修复后（托管键迁移会清掉工作区 .env 的四键），读写权威源是全局
配置文件——测试与生产 lifespan 接线对齐：显式设 ``app.state.env_file``
指向 ``app_config_env_path()``，文件内容断言一律落在全局文件上。

A2 扩展：MANAGED_KEYS 增至六键（+ PARALLEL_API_KEY / IMAGE_API_KEY），
新增带类型的 EXTENDED_KEYS（图像端点 / 预算节奏 / 审批权限），覆盖
GET 掩码、PUT 合法与非法值、os.environ 即时生效三块。
"""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from research_assistant.config import app_config_env_path  # noqa: E402
from research_assistant.web.settings import EXTENDED_KEYS  # noqa: E402
from research_assistant.web.settings import router as settings_router  # noqa: E402

FULL_KEY = "sk-abcdefghijklmnop1234"
PARALLEL_KEY = "para-ws-abcdefghijklmnop"
IMAGE_KEY = "img-nvapi-1234567890abcd"

#: 保存接口会同步 os.environ（免重启）——逐用例清理，防跨文件泄漏。
_TOUCHED_ENV = (
    "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_PROVIDER",
    "PARALLEL_API_KEY", "IMAGE_API_KEY",
) + tuple(EXTENDED_KEYS)


@pytest.fixture(autouse=True)
def _isolated_appdata(isolated_appdata):
    """R8：settings 读写会触碰全局配置目录——一律重定向到 tmp。"""


@pytest.fixture(autouse=True)
def _clean_environ(monkeypatch):
    for key in _TOUCHED_ENV:
        monkeypatch.delenv(key, raising=False)


def _app(tmp_path) -> TestClient:
    app = FastAPI()
    app.include_router(settings_router, prefix="/api")
    app.state.cwd = tmp_path
    # 与生产 lifespan 同接线：env_file 指向全局配置（托管键权威源）。
    app.state.env_file = app_config_env_path()
    return TestClient(app)


def _payload(**over):
    base = {
        "llm_api_key": FULL_KEY,
        "llm_base_url": "https://api.deepseek.com",
        "llm_model": "deepseek-chat",
        "llm_provider": "openai",
    }
    base.update(over)
    return base


def _ext_payload(**over):
    """A2 扩展键的合法样例值（叠加在 LLM 四键之上）。"""
    base = {
        **_payload(),
        "parallel_api_key": PARALLEL_KEY,
        "image_api_key": IMAGE_KEY,
        "image_base_url": "https://apihub.agnes-ai.com/v1",
        "image_model": "agnes-image-2.0-flash",
        "ra_max_cost_usd": 5,
        "ra_max_tokens": 100000,
        "ra_max_turns": 40,
        "llm_request_interval": 1.5,
        "ra_llm_first_byte_timeout": 30,
        "ra_approval_mode": "interactive",
        "ra_permission_mode": "off",
    }
    base.update(over)
    return base


class TestGetSettings:
    def test_missing_env_reports_unconfigured(self, tmp_path):
        body = _app(tmp_path).get("/api/settings").json()
        assert body["configured"] is False
        assert body["llm_api_key_masked"] == ""
        assert body["llm_model"] == ""

    def test_key_masked_full_plaintext_never_returned(self, tmp_path):
        (tmp_path / ".env").write_text(f"LLM_API_KEY={FULL_KEY}\n", encoding="utf-8")
        r = _app(tmp_path).get("/api/settings")
        assert r.json()["configured"] is True
        assert FULL_KEY not in r.text
        assert r.json()["llm_api_key_masked"] == "sk-a***1234"

    def test_short_key_fully_masked(self, tmp_path):
        (tmp_path / ".env").write_text("LLM_API_KEY=short1\n", encoding="utf-8")
        body = _app(tmp_path).get("/api/settings").json()
        assert body["llm_api_key_masked"] == "***"

    def test_quoted_values_unwrapped(self, tmp_path):
        (tmp_path / ".env").write_text('LLM_MODEL="deepseek-chat"\n', encoding="utf-8")
        assert _app(tmp_path).get("/api/settings").json()["llm_model"] == "deepseek-chat"


class TestSaveSettings:
    def test_save_roundtrip(self, tmp_path):
        c = _app(tmp_path)
        r = c.post("/api/settings", json=_payload())
        assert r.json()["ok"] is True
        env = app_config_env_path().read_text(encoding="utf-8")  # 权威源：全局配置
        for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_PROVIDER"):
            assert f"{key}=" in env
        assert c.get("/api/settings").json()["configured"] is True

    def test_workspace_keys_migrate_to_global_on_first_read(self, tmp_path):
        """缺陷 G 收尾：老用户工作区四键首次打开设置页即上移全局并清源。"""
        (tmp_path / ".env").write_text(f"LLM_API_KEY={FULL_KEY}\n", encoding="utf-8")
        c = _app(tmp_path)
        body = c.get("/api/settings").json()
        assert body["configured"] is True  # 迁移后从全局读到
        genv = app_config_env_path().read_text(encoding="utf-8")
        assert f"LLM_API_KEY={FULL_KEY}" in genv  # 已上移
        wenv = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "LLM_API_KEY" not in wenv  # 工作区已清源（防旧 Key 复活）
        assert (tmp_path / ".env.ra-migration.bak").exists()  # 首次清理留备份

    def test_rewrite_preserves_unknown_lines_and_comments(self, tmp_path):
        gpath = app_config_env_path()
        gpath.parent.mkdir(parents=True, exist_ok=True)
        gpath.write_text(
            "# my custom setup\nLLM_MODEL=old-model\nPARALLEL_API_KEY=para-keep-me\n",
            encoding="utf-8",
        )
        c = _app(tmp_path)
        c.post("/api/settings", json=_payload(llm_model="new-model"))
        env = gpath.read_text(encoding="utf-8")
        assert "# my custom setup" in env  # 注释保留
        assert "PARALLEL_API_KEY=para-keep-me" in env  # 无关键保留
        assert "LLM_MODEL=new-model" in env  # 托管键原地更新
        assert "old-model" not in env  # 不残留旧值
        assert env.count("LLM_MODEL=") == 1  # 不重复追加

    def test_duplicate_managed_keys_collapsed_to_first(self, tmp_path):
        gpath = app_config_env_path()
        gpath.parent.mkdir(parents=True, exist_ok=True)
        gpath.write_text("LLM_MODEL=a\nLLM_MODEL=b\n", encoding="utf-8")
        _app(tmp_path).post("/api/settings", json=_payload(llm_model="z"))
        env = gpath.read_text(encoding="utf-8")
        assert env.count("LLM_MODEL=") == 1
        assert "LLM_MODEL=z" in env

    def test_empty_key_keeps_existing(self, tmp_path):
        c = _app(tmp_path)
        c.post("/api/settings", json=_payload())
        r = c.post("/api/settings", json=_payload(llm_api_key="", llm_model="qwen-plus"))
        assert r.json()["ok"] is True
        env = app_config_env_path().read_text(encoding="utf-8")
        assert f"LLM_API_KEY={FULL_KEY}" in env  # 原 Key 未丢
        assert "LLM_MODEL=qwen-plus" in env

    def test_empty_key_without_existing_rejected(self, tmp_path):
        r = _app(tmp_path).post("/api/settings", json=_payload(llm_api_key=""))
        assert r.status_code == 422

    def test_state_env_file_takes_precedence(self, tmp_path, isolated_appdata):
        """R8：lifespan 会把 env_file 指到全局配置——state 覆写必须生效。"""
        custom = isolated_appdata / "custom.env"
        custom.write_text("LLM_API_KEY=sk-custom-1234\n", encoding="utf-8")
        app = FastAPI()
        app.include_router(settings_router, prefix="/api")
        app.state.cwd = tmp_path
        app.state.env_file = custom
        c = TestClient(app)

        body = c.get("/api/settings").json()
        assert body["configured"] is True
        assert body["llm_api_key_masked"] == "sk-c***1234"

        # 保存也写进 env_file 指向的文件，而非工作区
        c.post("/api/settings", json=_payload(llm_model="m1"))
        assert "LLM_MODEL=m1" in custom.read_text(encoding="utf-8")
        assert not (tmp_path / ".env").exists()


class TestTestEndpoint:
    @pytest.fixture()
    def fake_factory(self, monkeypatch):
        """替换 create_llm_client；返回可编程的假 client 工厂。"""
        calls = {}

        class FakeClient:
            programmed_exc = None
            reply = "正常"

            def __init__(self, **kw):
                calls["kwargs"] = kw

            async def chat(self, messages, **kwargs):
                calls["messages"] = messages
                if type(self).programmed_exc:
                    raise type(self).programmed_exc
                from research_assistant.llm.base import LLMResponse

                return LLMResponse(content=type(self).reply)

            async def close(self):
                pass

        monkeypatch.setattr(
            "research_assistant.llm.factory.create_llm_client", lambda **kw: FakeClient(**kw)
        )
        return {"calls": calls, "cls": FakeClient}

    def test_ok_reply(self, tmp_path, fake_factory):
        r = _app(tmp_path).post("/api/settings/test", json=_payload())
        body = r.json()
        assert body["ok"] is True
        assert body["model"] == "deepseek-chat"
        assert "正常" in body["reply"]
        assert fake_factory["calls"]["kwargs"]["model"] == "deepseek-chat"

    def test_error_surfaced_not_raised(self, tmp_path, fake_factory):
        fake_factory["cls"].programmed_exc = RuntimeError("401 bad key")
        body = _app(tmp_path).post("/api/settings/test", json=_payload()).json()
        assert body["ok"] is False
        assert "401 bad key" in body["error"]

    def test_empty_key_everywhere_422(self, tmp_path):
        r = _app(tmp_path).post("/api/settings/test", json=_payload(llm_api_key=""))
        assert r.status_code == 422

    def test_empty_key_falls_back_to_configured(self, tmp_path, fake_factory):
        c = _app(tmp_path)
        c.post("/api/settings", json=_payload())
        body = c.post("/api/settings/test", json=_payload(llm_api_key="", llm_base_url="")).json()
        assert body["ok"] is True


# ---------------------------------------------------------------------------
# A2 扩展键：GET 掩码 / PUT 校验与落盘 / os.environ 即时生效
# ---------------------------------------------------------------------------

class TestGetExtendedSettings:
    def test_secret_keys_masked_plaintext_never_leaks(self, tmp_path):
        gpath = app_config_env_path()
        gpath.parent.mkdir(parents=True, exist_ok=True)
        gpath.write_text(
            f"PARALLEL_API_KEY={PARALLEL_KEY}\nIMAGE_API_KEY={IMAGE_KEY}\n",
            encoding="utf-8",
        )
        r = _app(tmp_path).get("/api/settings")
        assert PARALLEL_KEY not in r.text
        assert IMAGE_KEY not in r.text
        body = r.json()
        # 掩码规则与 LLM_API_KEY 一致：首 4 + *** + 尾 4
        assert body["parallel_api_key_masked"] == "para***mnop"
        assert body["image_api_key_masked"] == "img-***abcd"

    def test_non_secret_values_returned_plain(self, tmp_path):
        gpath = app_config_env_path()
        gpath.parent.mkdir(parents=True, exist_ok=True)
        gpath.write_text(
            "IMAGE_BASE_URL=https://apihub.agnes-ai.com/v1\n"
            "IMAGE_MODEL=agnes-image-2.0-flash\n",
            encoding="utf-8",
        )
        body = _app(tmp_path).get("/api/settings").json()
        # 长 str 键不做掩码（掩码只作用于 *_API_KEY）
        assert body["image_base_url"] == "https://apihub.agnes-ai.com/v1"
        assert body["image_model"] == "agnes-image-2.0-flash"

    def test_numeric_fields_parsed_to_numbers(self, tmp_path):
        gpath = app_config_env_path()
        gpath.parent.mkdir(parents=True, exist_ok=True)
        gpath.write_text(
            "RA_MAX_COST_USD=12.5\nRA_MAX_TOKENS=100000\nLLM_REQUEST_INTERVAL=0\n",
            encoding="utf-8",
        )
        body = _app(tmp_path).get("/api/settings").json()
        assert body["ra_max_cost_usd"] == 12.5
        assert body["ra_max_tokens"] == 100000  # 整数值回 int，便于表单预填
        assert body["llm_request_interval"] == 0

    def test_unset_extended_fields_are_blank(self, tmp_path):
        body = _app(tmp_path).get("/api/settings").json()
        assert body["ra_max_cost_usd"] == ""
        assert body["ra_approval_mode"] == ""
        assert body["parallel_api_key_masked"] == ""


class TestSaveExtendedSettings:
    def test_put_roundtrip_all_extended_keys(self, tmp_path):
        c = _app(tmp_path)
        r = c.put("/api/settings", json=_ext_payload())  # 前端保存走 PUT 别名
        assert r.json()["ok"] is True
        env = app_config_env_path().read_text(encoding="utf-8")
        for key in (
            "PARALLEL_API_KEY", "IMAGE_API_KEY", "IMAGE_BASE_URL", "IMAGE_MODEL",
            "RA_MAX_COST_USD=5.0", "RA_MAX_TOKENS=100000", "RA_MAX_TURNS=40",
            "LLM_REQUEST_INTERVAL=1.5", "RA_LLM_FIRST_BYTE_TIMEOUT=30.0",
            "RA_APPROVAL_MODE=interactive", "RA_PERMISSION_MODE=off",
        ):
            assert key in env
        body = c.get("/api/settings").json()
        assert body["ra_max_cost_usd"] == 5.0
        assert body["ra_approval_mode"] == "interactive"

    def test_absent_extended_keys_untouched(self, tmp_path):
        """老客户端只发 LLM 四键：扩展配置不得被意外清掉。"""
        c = _app(tmp_path)
        c.post("/api/settings", json=_ext_payload())
        c.post("/api/settings", json=_payload(llm_model="qwen-plus"))
        env = app_config_env_path().read_text(encoding="utf-8")
        assert "RA_MAX_COST_USD=5.0" in env
        assert f"PARALLEL_API_KEY={PARALLEL_KEY}" in env

    def test_explicit_empty_clears_extended_key(self, tmp_path):
        c = _app(tmp_path)
        c.post("/api/settings", json=_ext_payload())
        c.put("/api/settings", json=_ext_payload(ra_approval_mode="", ra_max_turns=""))
        env = app_config_env_path().read_text(encoding="utf-8")
        assert "RA_APPROVAL_MODE=" in env and "interactive" not in env
        body = c.get("/api/settings").json()
        assert body["ra_approval_mode"] == ""
        assert body["ra_max_turns"] == ""

    def test_empty_new_secret_key_keeps_existing(self, tmp_path):
        c = _app(tmp_path)
        c.post("/api/settings", json=_ext_payload())
        c.put("/api/settings", json=_ext_payload(parallel_api_key="", image_api_key=""))
        env = app_config_env_path().read_text(encoding="utf-8")
        # 密钥类留空 = 沿用（与 LLM_API_KEY 同一契约），不会写空
        assert f"PARALLEL_API_KEY={PARALLEL_KEY}" in env
        assert f"IMAGE_API_KEY={IMAGE_KEY}" in env

    def test_unknown_payload_fields_ignored(self, tmp_path):
        r = _app(tmp_path).post(
            "/api/settings", json={**_payload(), "future_key": "whatever"}
        )
        assert r.json()["ok"] is True


class TestExtendedValidation:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("ra_max_cost_usd", 0),          # 成本必须 > 0
            ("ra_max_cost_usd", -1),
            ("ra_max_tokens", 0),            # token/turns 必须 >= 1
            ("ra_max_tokens", 10.5),         # 且为整数
            ("ra_max_tokens", "abc"),        # 必须是数字
            ("ra_max_turns", 0),
            ("llm_request_interval", -0.5),  # 间隔 >= 0
            ("ra_llm_first_byte_timeout", 3),  # 超时 >= 5 秒
            ("ra_approval_mode", "yolo"),
            ("ra_permission_mode", "allow_all"),
        ],
    )
    def test_invalid_value_rejected_400_chinese(self, tmp_path, field, value):
        r = _app(tmp_path).post("/api/settings", json=_ext_payload(**{field: value}))
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert detail and any("一" <= ch <= "鿿" for ch in detail)  # 中文错误

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("ra_max_cost_usd", 0.01),   # 边界：成本 > 0 即合法
            ("ra_max_tokens", 1),
            ("ra_max_turns", 1),
            ("llm_request_interval", 0),  # 边界：间隔可以为 0
            ("ra_llm_first_byte_timeout", 5),  # 边界：恰为下限
            ("ra_permission_mode", "deny_dangerous"),
            ("image_model", ""),
        ],
    )
    def test_boundary_values_accepted(self, tmp_path, field, value):
        r = _app(tmp_path).post("/api/settings", json=_ext_payload(**{field: value}))
        assert r.status_code == 200, r.text

    def test_invalid_value_leaves_file_untouched(self, tmp_path):
        """先整体校验后落盘：一个非法值不能让其它合法键先写入。"""
        gpath = app_config_env_path()
        gpath.parent.mkdir(parents=True, exist_ok=True)
        gpath.write_text("LLM_MODEL=keep-me\n", encoding="utf-8")
        before = gpath.read_text(encoding="utf-8")
        r = _app(tmp_path).post(
            "/api/settings", json=_ext_payload(ra_max_tokens=-3)
        )
        assert r.status_code == 400
        assert gpath.read_text(encoding="utf-8") == before


class TestEnvImmediateEffect:
    def test_saved_keys_written_into_environ(self, tmp_path):
        c = _app(tmp_path)
        c.post("/api/settings", json=_ext_payload())
        import os

        assert os.environ["PARALLEL_API_KEY"] == PARALLEL_KEY
        assert os.environ["IMAGE_MODEL"] == "agnes-image-2.0-flash"
        assert os.environ["RA_MAX_COST_USD"] == "5.0"
        assert os.environ["RA_MAX_TOKENS"] == "100000"
        assert os.environ["LLM_REQUEST_INTERVAL"] == "1.5"
        assert os.environ["RA_LLM_FIRST_BYTE_TIMEOUT"] == "30.0"
        assert os.environ["RA_APPROVAL_MODE"] == "interactive"

    def test_cleared_key_removed_from_environ(self, tmp_path, monkeypatch):
        import os

        monkeypatch.setenv("RA_MAX_TURNS", "7")
        c = _app(tmp_path)
        c.post("/api/settings", json=_ext_payload())
        assert os.environ["RA_MAX_TURNS"] == "40"  # 保存覆盖
        c.post("/api/settings", json=_ext_payload(ra_max_turns=""))
        assert "RA_MAX_TURNS" not in os.environ  # 清空 = 从环境移除（免重启）
