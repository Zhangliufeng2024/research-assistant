"""R17 阶段4 思考链通道测试：provider 解析 + WS 帧 channel 字段。

红线：思考增量绝不混入正文（content / partial_text / history）。
协议：text 帧加可选 channel 字段（"thought" / "plan"），不加新帧型。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import research_assistant.web.chat as chat_mod  # noqa: E402
from research_assistant.agent import AgentResult  # noqa: E402
from research_assistant.llm.anthropic import AnthropicClient  # noqa: E402
from research_assistant.llm.openai_compat import OpenAICompatClient  # noqa: E402
from research_assistant.web.chat import router  # noqa: E402


def _sse(lines: list[str]) -> httpx.Response:
    body = "\n".join(lines) + "\n"
    return httpx.Response(
        200, content=body.encode("utf-8"),
        headers={"content-type": "text/event-stream"},
    )


class TestOpenAIThought:
    @pytest.mark.asyncio
    async def test_reasoning_content_routed_to_on_thought(self, monkeypatch):
        monkeypatch.setenv("LLM_REQUEST_INTERVAL", "0")
        client = OpenAICompatClient(
            api_key="k", base_url="http://fake.local", model="m",
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return _sse([
                'data: {"choices":[{"delta":{"reasoning_content":"先想"}}]}',
                'data: {"choices":[{"delta":{"reasoning_content":"再想"}}]}',
                'data: {"choices":[{"delta":{"content":"正文"}}]}',
                "data: [DONE]",
            ])

        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        thoughts: list[str] = []
        chunks: list[str] = []
        try:
            resp = await client.chat(
                [{"role": "user", "content": "hi"}],
                on_chunk=chunks.append, on_thought=thoughts.append,
            )
        finally:
            await client.close()
        assert "".join(thoughts) == "先想再想"
        assert "".join(chunks) == "正文"
        assert resp.content == "正文"  # 红线：思考不混入正文

    @pytest.mark.asyncio
    async def test_reason_content_alias(self, monkeypatch):
        """部分端点用 reason_content 字段名。"""
        monkeypatch.setenv("LLM_REQUEST_INTERVAL", "0")
        client = OpenAICompatClient(
            api_key="k", base_url="http://fake.local", model="m",
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return _sse([
                'data: {"choices":[{"delta":{"reason_content":"想"}}]}',
                "data: [DONE]",
            ])

        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        thoughts: list[str] = []
        try:
            await client.chat(
                [{"role": "user", "content": "hi"}],
                on_chunk=lambda t: None, on_thought=thoughts.append,
            )
        finally:
            await client.close()
        assert thoughts == ["想"]

    @pytest.mark.asyncio
    async def test_no_callback_no_crash(self, monkeypatch):
        """不传 on_thought 时 reasoning_content 静默忽略（旧行为）。"""
        monkeypatch.setenv("LLM_REQUEST_INTERVAL", "0")
        client = OpenAICompatClient(
            api_key="k", base_url="http://fake.local", model="m",
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return _sse([
                'data: {"choices":[{"delta":{"reasoning_content":"想","content":"文"}}]}',
                "data: [DONE]",
            ])

        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            resp = await client.chat(
                [{"role": "user", "content": "hi"}], on_chunk=lambda t: None,
            )
        finally:
            await client.close()
        assert resp.content == "文"


class TestAnthropicThought:
    @pytest.mark.asyncio
    async def test_thinking_delta_routed_to_on_thought(self, monkeypatch):
        monkeypatch.setenv("LLM_REQUEST_INTERVAL", "0")
        client = AnthropicClient(
            api_key="k", base_url="http://fake.local", model="m",
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return _sse([
                'event: content_block_start\ndata: {"type":"content_block_start","content_block":{"type":"thinking"}}',
                'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"推理"}}',
                'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"答案"}}',
                'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":3}}',
            ])

        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        thoughts: list[str] = []
        chunks: list[str] = []
        try:
            resp = await client.chat(
                [{"role": "user", "content": "hi"}],
                on_chunk=chunks.append, on_thought=thoughts.append,
            )
        finally:
            await client.close()
        assert thoughts == ["推理"]
        assert chunks == ["答案"]
        assert resp.content == "答案"


# ---------------------------------------------------------------------------
# WS 帧：channel 字段端到端
# ---------------------------------------------------------------------------


def _make_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.include_router(router)
    app.state.cwd = tmp_path
    app.state.model = "test-model"
    app.state.output_folder = tmp_path / "writing_outputs"
    app.state.active_tasks = {}
    return app


class _FakeLLM:
    model = "fake-model"

    async def close(self) -> None:
        return None


class TestThoughtFrames:
    def test_thought_frame_carries_channel_and_not_in_history(
        self, tmp_path, monkeypatch,
    ):
        async def behavior(kw) -> AgentResult:
            await kw["on_thought"]("我在思考")
            await kw["on_text"]("最终回答")
            return AgentResult(text_output="最终回答", turns=1, stop_reason="completed")

        def fake_run_agent(**kwargs):
            return behavior(kwargs)

        monkeypatch.setattr(chat_mod, "run_agent", fake_run_agent)
        monkeypatch.setattr(
            chat_mod, "build_llm_client", lambda model=None: _FakeLLM(),
        )
        with TestClient(_make_app(tmp_path)) as client:
            with client.websocket_connect("/ws/chat") as ws:
                hello = ws.receive_json()
                assert hello["type"] == "connected"
                sid = hello["session_id"]
                ws.send_json({"action": "user", "text": "你好"})
                frames = []
                for _ in range(50):
                    msg = ws.receive_json()
                    frames.append(msg)
                    if msg.get("type") == "result":
                        break
        text_frames = [f for f in frames if f.get("type") == "text"]
        thought = [f for f in text_frames if f.get("channel") == "thought"]
        normal = [f for f in text_frames if not f.get("channel")]
        assert [f["delta"] for f in thought] == ["我在思考"]
        assert [f["delta"] for f in normal] == ["最终回答"]
        # 红线：落盘历史不含思考
        history = json.loads(
            (tmp_path / ".ra" / "sessions" / sid / "history.json").read_text(
                encoding="utf-8",
            ),
        )["messages"]
        assert all("思考" not in m["content"] for m in history)
        assert history[-1]["content"] == "最终回答"
