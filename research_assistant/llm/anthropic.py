"""Anthropic Messages API client using httpx."""

import json
import uuid
from typing import Any

import httpx

from .base import LLMClient, LLMResponse, ToolCall, TokenUsage, _throttle_llm

ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_API_VERSION = "2023-06-01"


def _convert_tools_to_anthropic(tools: list[dict] | None) -> list[dict]:
    """Convert unified tool schemas to Anthropic's tool format."""
    if not tools:
        return []
    result = []
    for t in tools:
        result.append({
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": t.get("parameters", t.get("input_schema", {"type": "object", "properties": {}})),
        })
    return result


def _build_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Convert unified message format to Anthropic's message format.

    Handles tool_result blocks by wrapping them in the Anthropic content format.
    """
    result = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")

        if role == "tool":
            tool_result = {
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id", ""),
                "content": content if isinstance(content, str) else json.dumps(content),
            }
            if msg.get("is_error"):
                tool_result["is_error"] = True
            if result and result[-1]["role"] == "user":
                existing = result[-1]["content"]
                if isinstance(existing, str):
                    result[-1]["content"] = [{"type": "text", "text": existing}, tool_result]
                elif isinstance(existing, list):
                    existing.append(tool_result)
                else:
                    result[-1]["content"] = [tool_result]
            else:
                result.append({"role": "user", "content": [tool_result]})
            continue

        if role == "assistant" and isinstance(content, list):
            result.append({"role": "assistant", "content": content})
            continue

        if role == "assistant" and msg.get("tool_calls"):
            blocks: list[dict] = []
            if content:
                blocks.append({"type": "text", "text": content})
            for tc in msg["tool_calls"]:
                blocks.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["arguments"] if isinstance(tc["arguments"], dict) else json.loads(tc["arguments"]),
                })
            result.append({"role": "assistant", "content": blocks})
            continue

        result.append({"role": role, "content": content})
    return result


class AnthropicClient(LLMClient):
    """Anthropic Messages API client."""

    def __init__(self, api_key: str, base_url: str = "", model: str = "claude-sonnet-4-6"):
        self.api_key = api_key
        self.base_url = (base_url or ANTHROPIC_DEFAULT_BASE_URL).rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))

    async def chat(
        self,
        messages: list[dict],
        *,
        system: str = "",
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 16384,
    ) -> LLMResponse:
        url = f"{self.base_url}/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }

        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": _build_anthropic_messages(messages),
        }
        if system:
            body["system"] = system
        anthropic_tools = _convert_tools_to_anthropic(tools)
        if anthropic_tools:
            body["tools"] = anthropic_tools

        await _throttle_llm()
        resp = await self._client.post(url, headers=headers, json=body)

        if resp.status_code != 200:
            raise RuntimeError(f"Anthropic API error ({resp.status_code}): {resp.text}")

        data = resp.json()
        return self._parse_response(data)

    def _parse_response(self, data: dict) -> LLMResponse:
        content_text = ""
        tool_calls: list[ToolCall] = []

        for block in data.get("content", []):
            if block.get("type") == "text":
                content_text += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.get("id", str(uuid.uuid4())),
                    name=block.get("name", ""),
                    arguments=block.get("input", {}),
                ))

        stop_reason_map = {
            "end_turn": "end_turn",
            "tool_use": "tool_use",
            "max_tokens": "max_tokens",
            "stop_sequence": "end_turn",
        }
        raw_stop = data.get("stop_reason", "end_turn")
        stop_reason = stop_reason_map.get(raw_stop, raw_stop)

        usage_data = data.get("usage", {})
        usage = TokenUsage(
            input_tokens=usage_data.get("input_tokens", 0),
            output_tokens=usage_data.get("output_tokens", 0),
            cache_creation_input_tokens=usage_data.get("cache_creation_input_tokens", 0),
            cache_read_input_tokens=usage_data.get("cache_read_input_tokens", 0),
        )

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
        )

    async def close(self) -> None:
        await self._client.aclose()
