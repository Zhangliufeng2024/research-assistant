"""OpenAI-compatible Chat Completions API client using httpx."""

import asyncio
import json
import uuid
from typing import Any, Optional

import httpx

from .base import LLMClient, LLMResponse, ToolCall, OnChunkCallback, _throttle_llm
from ..models import TokenUsage
from ..constants import DEFAULT_OPENAI_MODEL, HTTP_TIMEOUT_SECONDS, HTTP_CONNECT_TIMEOUT_SECONDS

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

    def __init__(self, api_key: str, base_url: str = "", model: str = DEFAULT_OPENAI_MODEL):
        self.api_key = api_key
        self.base_url = (base_url or OPENAI_DEFAULT_BASE_URL).rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(HTTP_TIMEOUT_SECONDS, connect=HTTP_CONNECT_TIMEOUT_SECONDS),
        )

    async def chat(
        self,
        messages: list[dict],
        *,
        system: str = "",
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        on_chunk: Optional[OnChunkCallback] = None,
    ) -> LLMResponse:
        base = self.base_url
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        url = f"{base}/chat/completions"
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

        if on_chunk is not None:
            body["stream"] = True
            return await self._chat_streaming(url, headers, body, on_chunk)

        resp = await self._client.post(url, headers=headers, json=body)

        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI-compatible API error ({resp.status_code}): {resp.text}")

        data = resp.json()
        return self._parse_response(data)

    async def _chat_streaming(
        self,
        url: str,
        headers: dict,
        body: dict,
        on_chunk: OnChunkCallback,
    ) -> LLMResponse:
        """Stream the OpenAI-compatible response via SSE, calling on_chunk for text deltas."""
        content_text = ""
        tool_calls_by_index: dict[int, dict] = {}
        stop_reason = "end_turn"
        usage = TokenUsage()

        async with self._client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                await resp.aread()
                raise RuntimeError(f"OpenAI-compatible API error ({resp.status_code}): {resp.text}")

            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if chunk.get("usage"):
                    u = chunk["usage"]
                    usage.input_tokens = u.get("prompt_tokens", 0)
                    usage.output_tokens = u.get("completion_tokens", 0)

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                choice = choices[0]
                delta = choice.get("delta", {})

                text = delta.get("content")
                if text:
                    content_text += text
                    result = on_chunk(text)
                    if asyncio.iscoroutine(result):
                        await result

                for tc_delta in delta.get("tool_calls", []):
                    idx = tc_delta.get("index", 0)
                    if idx not in tool_calls_by_index:
                        tool_calls_by_index[idx] = {
                            "id": tc_delta.get("id", str(uuid.uuid4())),
                            "name": tc_delta.get("function", {}).get("name", ""),
                            "arguments": "",
                        }
                    else:
                        fn = tc_delta.get("function", {})
                        if fn.get("name"):
                            tool_calls_by_index[idx]["name"] = fn["name"]
                        if tc_delta.get("id"):
                            tool_calls_by_index[idx]["id"] = tc_delta["id"]
                    arg_chunk = tc_delta.get("function", {}).get("arguments", "")
                    if arg_chunk:
                        tool_calls_by_index[idx]["arguments"] += arg_chunk

                finish = choice.get("finish_reason")
                if finish:
                    stop_reason_map = {
                        "stop": "end_turn",
                        "tool_calls": "tool_use",
                        "length": "max_tokens",
                        "content_filter": "end_turn",
                    }
                    stop_reason = stop_reason_map.get(finish, finish)

        tool_calls: list[ToolCall] = []
        for idx in sorted(tool_calls_by_index):
            tc = tool_calls_by_index[idx]
            try:
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                args = {"raw": tc["arguments"]}
            tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], arguments=args))

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
        )

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
