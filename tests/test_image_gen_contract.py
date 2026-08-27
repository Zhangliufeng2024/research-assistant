"""Agnes 生图 API 契约锁（R15 内置 agnes-image-2.0-flash）。

用户 2026-08 提供的端点契约：
    POST {base}/images/generations  body {model, prompt, size, return_base64:true}
    → {"created": ..., "data": [{"url": null, "b64_json": "...", "revised_prompt": null}]}

历史坑：两个技能脚本曾发 OpenAI 风格的 response_format/n 字段（该端点不认），
且用 ``"url" in first`` 判断下载分支——Agnes 正常响应里 url 是 **null**，
b64 缺失时会拿 None 去 requests.get 直接炸。这里把 wire 契约和两条解析路径都钉死。
"""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
GEN_IMAGE = REPO / ".claude" / "skills" / "generate-image" / "scripts" / "generate_image.py"
SCHEMATIC_AI = REPO / ".claude" / "skills" / "scientific-schematics" / "scripts" / "generate_schematic_ai.py"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-image-payload"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    """requests.Response 的最小替身：200 + 固定 JSON。"""

    def __init__(self, payload: dict[str, Any]):
        self.status_code = 200
        self.headers: dict[str, str] = {}
        self._payload = payload
        self.text = ""

    def json(self) -> dict[str, Any]:
        return self._payload


def _agnes_response(b64: str | None = None, url: str | None = None) -> dict[str, Any]:
    return {
        "created": 1780000000,
        "data": [{"url": url, "b64_json": b64, "revised_prompt": None}],
    }


@pytest.fixture()
def no_throttle(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("IMAGE_REQUEST_INTERVAL", "0")


# ---------------------------------------------------------------- generate_image.py
def test_default_model_is_agnes_image_2_0_flash():
    mod = _load_module(GEN_IMAGE, "gen_image_contract")
    assert mod.DEFAULT_IMAGE_MODEL == "agnes-image-2.0-flash"
    assert mod.DEFAULT_OPENAI_BASE_URL == "https://apihub.agnes-ai.com/v1"
    assert mod._is_images_api_model("agnes-image-2.0-flash")


def test_images_api_payload_matches_agnes_contract(no_throttle, monkeypatch):
    mod = _load_module(GEN_IMAGE, "gen_image_contract2")
    captured: dict[str, Any] = {}

    def fake_post(url, headers=None, json=None, timeout=None):  # noqa: A002
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = json
        return _FakeResponse(_agnes_response(b64=base64.b64encode(PNG_BYTES).decode()))

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    out = mod._generate_images_api(
        prompt="glass cube", model="agnes-image-2.0-flash",
        api_key="sk-test", base_url="https://apihub.agnes-ai.com/v1",
        scientific_mode=False,
    )

    assert captured["url"] == "https://apihub.agnes-ai.com/v1/images/generations"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    # 契约字段：return_base64=true；不得再发旧版 response_format / n
    assert captured["payload"] == {
        "model": "agnes-image-2.0-flash",
        "prompt": "glass cube",
        "size": "1024x1024",
        "return_base64": True,
    }
    assert out == PNG_BYTES


def test_images_api_rejects_null_url_without_b64(no_throttle, monkeypatch):
    """url=null 且无 b64：必须报错，而不是拿 None 去 requests.get。"""
    mod = _load_module(GEN_IMAGE, "gen_image_contract3")

    def fake_post(url, headers=None, json=None, timeout=None):  # noqa: A002
        return _FakeResponse(_agnes_response(b64=None, url=None))

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    with pytest.raises(RuntimeError):
        mod._generate_images_api(
            prompt="x", model="agnes-image-2.0-flash",
            api_key="k", base_url="http://mock/v1", scientific_mode=False,
        )


# ------------------------------------------------- generate_schematic_ai.py
def test_schematic_defaults_and_payload(no_throttle, monkeypatch):
    monkeypatch.delenv("IMAGE_MODEL", raising=False)
    monkeypatch.delenv("IMAGE_REVIEW_MODEL", raising=False)
    mod = _load_module(SCHEMATIC_AI, "schematic_ai_contract")
    gen = mod.ScientificSchematicGenerator(api_key="sk-test")
    assert gen.image_model == "agnes-image-2.0-flash"
    assert gen.review_model == "agnes-2.0-flash"

    captured: dict[str, Any] = {}

    def fake_post(url, headers=None, json=None, timeout=None):  # noqa: A002
        captured["url"] = url
        captured["payload"] = json
        return _FakeResponse(_agnes_response(b64=base64.b64encode(PNG_BYTES).decode()))

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    out = gen._make_images_api_request(model="agnes-image-2.0-flash", prompt="prism", size="1024x768")

    assert captured["url"].endswith("/images/generations")
    assert captured["payload"]["return_base64"] is True
    assert "response_format" not in captured["payload"]
    assert "n" not in captured["payload"]
    assert captured["payload"]["size"] == "1024x768"
    assert out == PNG_BYTES


# ---------------------------------------------------------------- launcher.py
def test_launcher_builtin_defaults():
    from research_assistant.launcher import DEFAULTS

    assert DEFAULTS["IMAGE_BASE_URL"] == "https://apihub.agnes-ai.com/v1"
    assert DEFAULTS["IMAGE_MODEL"] == "agnes-image-2.0-flash"
    assert DEFAULTS["IMAGE_REVIEW_MODEL"] == "agnes-2.0-flash"
