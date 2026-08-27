"""Tests for research_assistant.llm — LLM client abstraction."""

import json

import httpx
import pytest

from research_assistant.llm.anthropic import (
    AnthropicClient,
    _build_anthropic_messages,
    _convert_tools_to_anthropic,
)
from research_assistant.llm.factory import create_llm_client, detect_provider
from research_assistant.llm.openai_compat import (
    OpenAICompatClient,
    _build_openai_messages,
    _convert_tools_to_openai,
)


class TestDetectProvider:
    def test_anthropic_key(self):
        assert detect_provider("sk-ant-abc123") == "anthropic"

    def test_openai_key(self):
        assert detect_provider("sk-abc123") == "openai"

    def test_explicit_override(self):
        assert detect_provider("sk-ant-abc123", "openai") == "openai"

    def test_empty_provider_uses_key(self):
        assert detect_provider("sk-ant-test", "") == "anthropic"


# ---------------------------------------------------------------------------
# A2：provider 三级探测（显式 > base_url 含 anthropic > sk-ant- 前缀 > openai）
# 动机：第三方 Anthropic 兼容网关的 key 往往不是 sk-ant- 前缀。
# ---------------------------------------------------------------------------

class TestDetectProviderBaseUrl:
    def test_anthropic_in_base_url_wins_over_openai_style_key(self):
        assert detect_provider("gw-key-123", "", "https://anthropic.gateway.example/v1") == "anthropic"

    def test_base_url_case_insensitive(self):
        assert detect_provider("gw-key-123", "", "https://api.ANTHROPIC.com") == "anthropic"

    def test_sk_ant_prefix_still_recognized_without_url_hint(self):
        assert detect_provider("sk-ant-api03-xyz", "", "https://example.com") == "anthropic"

    def test_gateway_key_without_hints_defaults_openai(self):
        assert detect_provider("gw-random-format", "") == "openai"

    def test_explicit_provider_beats_base_url(self):
        assert detect_provider("k", "openai", "https://anthropic.proxy.example") == "openai"

    def test_create_client_routes_by_base_url(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        client = create_llm_client(
            api_key="gateway-custom-key",
            base_url="https://anthropic-compatible.gateway.example",
            model="claude-sonnet-5",
        )
        assert isinstance(client, AnthropicClient)


class TestConvertToolsAnthropic:
    def test_empty(self):
        assert _convert_tools_to_anthropic(None) == []
        assert _convert_tools_to_anthropic([]) == []

    def test_converts_schema(self):
        tools = [{
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        }]
        result = _convert_tools_to_anthropic(tools)
        assert len(result) == 1
        assert result[0]["name"] == "read_file"
        assert "input_schema" in result[0]


class TestConvertToolsOpenAI:
    def test_empty(self):
        assert _convert_tools_to_openai(None) == []

    def test_converts_schema(self):
        tools = [{
            "name": "bash",
            "description": "Run command",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
        }]
        result = _convert_tools_to_openai(tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "bash"


class TestBuildAnthropicMessages:
    def test_simple_messages(self):
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        result = _build_anthropic_messages(msgs)
        assert result == msgs

    def test_tool_result_becomes_user(self):
        msgs = [
            {"role": "tool", "tool_call_id": "tc_1", "content": "file content"},
        ]
        result = _build_anthropic_messages(msgs)
        assert result[0]["role"] == "user"
        assert result[0]["content"][0]["type"] == "tool_result"

    def test_assistant_with_tool_calls(self):
        msgs = [{
            "role": "assistant",
            "content": "thinking...",
            "tool_calls": [{"id": "tc_1", "name": "bash", "arguments": {"command": "ls"}}],
        }]
        result = _build_anthropic_messages(msgs)
        assert result[0]["role"] == "assistant"
        content = result[0]["content"]
        assert any(b["type"] == "text" for b in content)
        assert any(b["type"] == "tool_use" for b in content)


class TestBuildOpenAIMessages:
    def test_adds_system_message(self):
        result = _build_openai_messages([], system="You are helpful.")
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are helpful."

    def test_tool_result_message(self):
        msgs = [{"role": "tool", "tool_call_id": "tc_1", "content": "result"}]
        result = _build_openai_messages(msgs)
        assert result[0]["role"] == "tool"

    def test_assistant_tool_calls(self):
        msgs = [{
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "tc_1", "name": "bash", "arguments": {"command": "ls"}}],
        }]
        result = _build_openai_messages(msgs)
        assert "tool_calls" in result[0]
        assert result[0]["tool_calls"][0]["function"]["name"] == "bash"


class TestAnthropicClientParse:
    def test_parse_text_response(self):
        client = AnthropicClient(api_key="test", model="test")
        data = {
            "content": [{"type": "text", "text": "Hello world"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        resp = client._parse_response(data)
        assert resp.content == "Hello world"
        assert resp.stop_reason == "end_turn"
        assert resp.usage.input_tokens == 10

    def test_parse_tool_use_response(self):
        client = AnthropicClient(api_key="test", model="test")
        data = {
            "content": [
                {"type": "text", "text": "Let me read that."},
                {"type": "tool_use", "id": "tc_1", "name": "read_file", "input": {"file_path": "/tmp/x"}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 20, "output_tokens": 15},
        }
        resp = client._parse_response(data)
        assert resp.content == "Let me read that."
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "read_file"
        assert resp.stop_reason == "tool_use"


class TestOpenAICompatClientParse:
    def test_parse_text_response(self):
        client = OpenAICompatClient(api_key="test", model="test")
        data = {
            "choices": [{"message": {"content": "Hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        resp = client._parse_response(data)
        assert resp.content == "Hello"
        assert resp.stop_reason == "end_turn"

    def test_parse_tool_call_response(self):
        client = OpenAICompatClient(api_key="test", model="test")
        data = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "tc_1",
                        "type": "function",
                        "function": {"name": "bash", "arguments": '{"command": "ls"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        resp = client._parse_response(data)
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "bash"
        assert resp.tool_calls[0].arguments == {"command": "ls"}
        assert resp.stop_reason == "tool_use"

    def test_empty_choices(self):
        client = OpenAICompatClient(api_key="test", model="test")
        resp = client._parse_response({"choices": []})
        assert resp.content == ""


class TestCreateLlmClient:
    def test_creates_anthropic(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-ant-test")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        client = create_llm_client()
        assert isinstance(client, AnthropicClient)

    def test_creates_openai(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-test")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        client = create_llm_client()
        assert isinstance(client, OpenAICompatClient)

    def test_raises_without_key(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with pytest.raises(ValueError):
            create_llm_client()


# ---------------------------------------------------------------------------
# 缺陷 D：OpenAI 流式计量（stream_options.include_usage + 400 自动降级）
# ---------------------------------------------------------------------------

def _sse(lines: list[str]) -> httpx.Response:
    body = "\n".join(lines) + "\n"
    return httpx.Response(
        200,
        content=body.encode("utf-8"),
        headers={"content-type": "text/event-stream"},
    )


def _openai_stream_client(responses: list[httpx.Response], calls: list):
    """按顺序回放 *responses* 的假 OpenAI 端点；请求体记录进 *calls*。"""
    idx = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content.decode("utf-8")))
        i = min(idx["i"], len(responses) - 1)
        idx["i"] += 1
        return responses[i]

    client = OpenAICompatClient(
        api_key="test-key", base_url="http://fake.local", model="test-model",
    )
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


class TestOpenAIStreamingUsage:
    @pytest.mark.asyncio
    async def test_final_usage_chunk_captured(self, monkeypatch):
        """末尾 usage chunk（空 choices）应归集进 TokenUsage，正文照常流出。"""
        monkeypatch.setenv("LLM_REQUEST_INTERVAL", "0")
        calls: list = []
        client = _openai_stream_client([
            _sse([
                'data: {"choices":[{"delta":{"content":"He"}}]}',
                'data: {"choices":[{"delta":{"content":"llo"}}]}',
                'data: {"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":7}}',
                "data: [DONE]",
            ]),
        ], calls)

        chunks: list[str] = []
        try:
            resp = await client.chat(
                [{"role": "user", "content": "hi"}], on_chunk=chunks.append,
            )
        finally:
            await client.close()

        assert "".join(chunks) == "Hello"
        assert resp.usage.input_tokens == 11
        assert resp.usage.output_tokens == 7
        # 流式请求必须带 stream_options.include_usage，否则拿不到 usage chunk
        assert calls[0]["stream"] is True
        assert calls[0]["stream_options"] == {"include_usage": True}

    @pytest.mark.asyncio
    async def test_endpoint_without_usage_chunk_still_parses(self, monkeypatch):
        """端点忽略 stream_options 时无 usage chunk：解析不受影响，用量为 0。"""
        monkeypatch.setenv("LLM_REQUEST_INTERVAL", "0")
        calls: list = []
        client = _openai_stream_client([
            _sse([
                'data: {"choices":[{"delta":{"content":"ok"}}]}',
                "data: [DONE]",
            ]),
        ], calls)

        try:
            resp = await client.chat(
                [{"role": "user", "content": "hi"}], on_chunk=lambda t: None,
            )
        finally:
            await client.close()

        assert resp.content == "ok"
        assert resp.usage.input_tokens == 0
        assert resp.usage.output_tokens == 0

    @pytest.mark.asyncio
    async def test_400_mentioning_stream_options_degrades_once(self, monkeypatch):
        """端点报 400 且报文含 stream_options：去掉该字段重发一次（只降一次）。"""
        monkeypatch.setenv("LLM_REQUEST_INTERVAL", "0")
        calls: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            if "stream_options" in body:
                calls.append(body)
                return httpx.Response(
                    400,
                    json={"error": {"message":
                         "Unrecognized request argument supplied: stream_options"}},
                )
            calls.append(body)
            return _sse([
                'data: {"choices":[{"delta":{"content":"fine"}}]}',
                "data: [DONE]",
            ])

        client = OpenAICompatClient(
            api_key="test-key", base_url="http://fake.local", model="test-model",
        )
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        try:
            resp = await client.chat(
                [{"role": "user", "content": "hi"}], on_chunk=lambda t: None,
            )
        finally:
            await client.close()

        assert resp.content == "fine"
        assert len(calls) == 2
        assert "stream_options" in calls[0]
        assert "stream_options" not in calls[1]

    @pytest.mark.asyncio
    async def test_unrelated_400_does_not_degrade(self, monkeypatch):
        """与 stream_options 无关的 400 不触发降级，直接抛类型化错误。"""
        from research_assistant.llm.errors import BadRequestError

        monkeypatch.setenv("LLM_REQUEST_INTERVAL", "0")
        calls: list = []
        client = _openai_stream_client([
            httpx.Response(400, json={"error": {"message": "invalid temperature"}}),
        ], calls)

        try:
            with pytest.raises(BadRequestError):
                await client.chat(
                    [{"role": "user", "content": "hi"}], on_chunk=lambda t: None,
                )
        finally:
            await client.close()
        assert len(calls) == 1
