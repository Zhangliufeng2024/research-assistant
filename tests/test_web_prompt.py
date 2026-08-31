"""Tests for R18 prompt-enhance API (POST /api/prompt/enhance).

Covers the contract that matters most: **the endpoint never raises and never
loses the user's text** — every failure path returns ``ok:false`` with a
Chinese reason so the Composer can keep the original draft intact.

App construction mirrors test_web_settings.py: bare FastAPI + hand-wired
``app.state`` (no lifespan). The LLM client is faked by monkeypatching
``research_assistant.llm.factory.create_llm_client`` — prompt.py imports it
lazily inside the handler, so the patch is picked up at call time.
"""

import asyncio

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from research_assistant.llm.base import LLMResponse  # noqa: E402
from research_assistant.web.prompt import MAX_INPUT_CHARS  # noqa: E402
from research_assistant.web.prompt import router as prompt_router  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_environ(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)


def _app() -> TestClient:
    app = FastAPI()
    app.include_router(prompt_router, prefix="/api")
    return TestClient(app)


@pytest.fixture()
def fake_factory(monkeypatch):
    """替换 create_llm_client；返回可编程的假 client 工厂。"""
    calls: dict = {}

    class FakeClient:
        reply = "研究目标：…\n输出类型：…"
        programmed_exc = None

        def __init__(self, **kw):
            calls["kwargs"] = kw

        async def chat(self, messages, **kwargs):
            calls["messages"] = messages
            calls["kwargs_chat"] = kwargs
            if type(self).programmed_exc:
                raise type(self).programmed_exc
            return LLMResponse(content=type(self).reply)

        async def close(self):
            calls["closed"] = True

    monkeypatch.setattr(
        "research_assistant.llm.factory.create_llm_client",
        lambda **kw: FakeClient(**kw),
    )
    return {"calls": calls, "cls": FakeClient}


class TestValidation:
    def test_empty_text_422(self):
        assert _app().post("/api/prompt/enhance", json={"text": "   "}).status_code == 422

    def test_missing_text_422(self):
        assert _app().post("/api/prompt/enhance", json={}).status_code == 422

    def test_oversized_text_422(self):
        r = _app().post("/api/prompt/enhance", json={"text": "x" * (MAX_INPUT_CHARS + 1)})
        assert r.status_code == 422
        assert "过长" in r.json()["detail"]

    def test_boundary_length_accepted(self, monkeypatch, fake_factory):
        monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
        r = _app().post("/api/prompt/enhance", json={"text": "x" * MAX_INPUT_CHARS})
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestSuccess:
    def test_returns_enhanced_text(self, monkeypatch, fake_factory):
        monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
        body = _app().post("/api/prompt/enhance", json={"text": "写篇论文"}).json()
        assert body["ok"] is True
        assert body["enhanced"] == "研究目标：…\n输出类型：…"
        assert body["model"]

    def test_system_prompt_is_sent(self, monkeypatch, fake_factory):
        """系统提示必须送达——否则模型会直接回答问题而不是改写提示词。"""
        monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
        _app().post("/api/prompt/enhance", json={"text": "写篇论文"})
        system = fake_factory["calls"]["kwargs_chat"].get("system", "")
        assert "科研提示词工程师" in system
        # 用户原文作为唯一 user 消息原样送达
        assert fake_factory["calls"]["messages"] == [{"role": "user", "content": "写篇论文"}]

    def test_client_always_closed(self, monkeypatch, fake_factory):
        """finally close()：不泄漏 httpx 连接池（api.py 的既有教训）。"""
        monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
        _app().post("/api/prompt/enhance", json={"text": "写篇论文"})
        assert fake_factory["calls"].get("closed") is True


class TestFailurePaths:
    def test_missing_api_key_returns_guidance(self):
        """未配置 Key 不是服务端错误：返回可操作的中文指引，前端 toast 引导。"""
        body = _app().post("/api/prompt/enhance", json={"text": "写篇论文"}).json()
        assert body["ok"] is False
        assert "API Key" in body["error"]

    def test_exception_surfaced_not_raised(self, monkeypatch, fake_factory):
        fake_factory["cls"].programmed_exc = RuntimeError("401 bad key")
        monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
        r = _app().post("/api/prompt/enhance", json={"text": "写篇论文"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert "401 bad key" in body["error"]

    def test_timeout_returns_chinese_reason(self, monkeypatch, fake_factory):
        async def _hang(self, messages, **kwargs):
            await asyncio.sleep(5)

        fake_factory["cls"].chat = _hang
        monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
        monkeypatch.setattr("research_assistant.web.prompt.ENHANCE_TIMEOUT_S", 0.01)
        body = _app().post("/api/prompt/enhance", json={"text": "写篇论文"}).json()
        assert body["ok"] is False
        assert "超时" in body["error"]

    def test_empty_model_reply_is_failure(self, monkeypatch, fake_factory):
        """模型返回空必须判失败——否则会把用户的原文清成空串。"""
        fake_factory["cls"].reply = "   "
        monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
        body = _app().post("/api/prompt/enhance", json={"text": "写篇论文"}).json()
        assert body["ok"] is False
        assert "未改动" in body["error"]

    def test_streamed_chunks_used_as_fallback(self, monkeypatch):
        """content 为空时回退到 on_chunk 累积（与 settings/test 同口径）。"""

        class StreamOnlyClient:
            def __init__(self, **kw):
                pass

            async def chat(self, messages, **kwargs):
                on_chunk = kwargs.get("on_chunk")
                for piece in ("结构化", "提示词"):
                    if on_chunk:
                        on_chunk(piece)
                return LLMResponse(content="")

            async def close(self):
                pass

        monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
        monkeypatch.setattr(
            "research_assistant.llm.factory.create_llm_client",
            lambda **kw: StreamOnlyClient(**kw),
        )
        body = _app().post("/api/prompt/enhance", json={"text": "写篇论文"}).json()
        assert body["ok"] is True
        assert body["enhanced"] == "结构化提示词"
