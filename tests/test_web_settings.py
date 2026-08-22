"""Tests for R6 settings API (/api/settings*, 图形化模型配置后端).

Covers: masking on read, .env rewrite preserving unknown lines/comments,
empty-key-means-keep-existing contract, connection-test endpoint with a
faked LLM client. App construction mirrors test_web_api.py: bare FastAPI +
hand-wired ``app.state.cwd`` (no lifespan).
"""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from research_assistant.web.settings import router as settings_router  # noqa: E402

FULL_KEY = "sk-abcdefghijklmnop1234"


def _app(tmp_path) -> TestClient:
    app = FastAPI()
    app.include_router(settings_router, prefix="/api")
    app.state.cwd = tmp_path
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
        env = (tmp_path / ".env").read_text(encoding="utf-8")
        for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_PROVIDER"):
            assert f"{key}=" in env
        assert c.get("/api/settings").json()["configured"] is True

    def test_rewrite_preserves_unknown_lines_and_comments(self, tmp_path):
        (tmp_path / ".env").write_text(
            "# my custom setup\n"
            "LLM_MODEL=old-model\n"
            "PARALLEL_API_KEY=para-keep-me\n",
            encoding="utf-8")
        c = _app(tmp_path)
        c.post("/api/settings", json=_payload(llm_model="new-model"))
        env = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "# my custom setup" in env                      # 注释保留
        assert "PARALLEL_API_KEY=para-keep-me" in env          # 无关键保留
        assert "LLM_MODEL=new-model" in env                    # 托管键原地更新
        assert "old-model" not in env                          # 不残留旧值
        assert env.count("LLM_MODEL=") == 1                    # 不重复追加

    def test_duplicate_managed_keys_collapsed_to_first(self, tmp_path):
        (tmp_path / ".env").write_text(
            "LLM_MODEL=a\nLLM_MODEL=b\n", encoding="utf-8")
        _app(tmp_path).post("/api/settings", json=_payload(llm_model="z"))
        env = (tmp_path / ".env").read_text(encoding="utf-8")
        assert env.count("LLM_MODEL=") == 1
        assert "LLM_MODEL=z" in env

    def test_empty_key_keeps_existing(self, tmp_path):
        c = _app(tmp_path)
        c.post("/api/settings", json=_payload())
        r = c.post("/api/settings", json=_payload(llm_api_key="", llm_model="qwen-plus"))
        assert r.json()["ok"] is True
        env = (tmp_path / ".env").read_text(encoding="utf-8")
        assert f"LLM_API_KEY={FULL_KEY}" in env                # 原 Key 未丢
        assert "LLM_MODEL=qwen-plus" in env

    def test_empty_key_without_existing_rejected(self, tmp_path):
        r = _app(tmp_path).post("/api/settings", json=_payload(llm_api_key=""))
        assert r.status_code == 422


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
            "research_assistant.llm.factory.create_llm_client",
            lambda **kw: FakeClient(**kw))
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
        body = c.post(
            "/api/settings/test",
            json=_payload(llm_api_key="", llm_base_url="")).json()
        assert body["ok"] is True
