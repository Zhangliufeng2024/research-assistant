"""OpenAI-compatible Chat Completions API client using httpx."""

import json
import uuid
from typing import Any

import httpx

from .base import LLMClient, LLMResponse, ToolCall, TokenUsage, _throttle_llm

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com"


def _convert_tools_to_openai(tools: list[dict] | None) -> list[dict]:
    """Convert unified tool schemas to OpenAI function-calling format."""
    if not tools:
        return []
    result = []
    for t in tools:
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", t.get("input_schema", {"type": "object", "properties": {}})),
            },
        })
    return result


def _build_openai_messages(messages: list[dict], system: str = "") -> list[dict]:
    """Convert unified message format to OpenAI's message format."""
    result = []
    if system:
        result.append({"role": "system", "content": system})

    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")

        if role == "tool":
            result.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", ""),
                "content": content if isinstance(content, str) else json.dumps(content),
            })
            continue

        if role == "assistant" and msg.get("tool_calls"):
            tc_list = []
            for tc in msg["tool_calls"]:
                args = tc["arguments"]
                if isinstance(args, dict):
                    args = json.dumps(args)
                tc_list.append({
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": args,
                    },
                })
            out: dict[str, Any] = {"role": "assistant", "tool_calls": tc_list}
            if content:
                out["content"] = content
            result.append(out)
            continue

        result.append({"role": role, "content": content})
    return result


class OpenAICompatClient(LLMClient):
    """OpenAI-compatible Chat Completions API client."""

    def __init__(self, api_key: str, base_url: str = "", model: str = "gpt-4o"):
        self.api_key = api_key
        self.base_url = (base_url or OPENAI_DEFAULT_BASE_URL).rstrip("/")
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
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        body: dict[str, Any] = {
            "model": self.model,
            "messages": _build_openai_messages(messages, system),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        openai_tools = _convert_tools_to_openai(tools)
        if openai_tools:
            body["tools"] = openai_tools

        await _throttle_llm()
        resp = await self._client.post(url, headers=headers, json=body)

        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI-compatible API error ({resp.status_code}): {resp.text}")

        data = resp.json()
        return self._parse_response(data)

    def _parse_response(self, data: dict) -> LLMResponse:
        choices = data.get("choices", [])
        if not choices:
            return LLMResponse(content="", stop_reason="end_turn")

        choice = choices[0]
        message = choice.get("message", {})

        content = message.get("content", "") or ""
        tool_calls: list[ToolCall] = []

        for tc in message.get("tool_calls", []):
            func = tc.get("function", {})
            args_raw = func.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {"raw": args_raw}
            tool_calls.append(ToolCall(
                id=tc.get("id", str(uuid.uuid4())),
                name=func.get("name", ""),
                arguments=args,
            ))

        finish_reason = choice.get("finish_reason", "stop")
        stop_reason_map = {
            "stop": "end_turn",
            "tool_calls": "tool_use",
            "length": "max_tokens",
            "content_filter": "end_turn",
        }
        stop_reason = stop_reason_map.get(finish_reason, finish_reason)

        usage_data = data.get("usage", {})
        usage = TokenUsage(
            input_tokens=usage_data.get("prompt_tokens", 0),
            output_tokens=usage_data.get("completion_tokens", 0),
        )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
        )

    async def close(self) -> None:
        await self._client.aclose()
