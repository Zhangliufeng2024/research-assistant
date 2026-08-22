"""Tests for research_assistant.llm — LLM client abstraction."""

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
