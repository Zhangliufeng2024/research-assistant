"""OpenAI-compatible Chat Completions API client using httpx."""

import asyncio
import json
import uuid
from typing import Any

import httpx

from ..constants import DEFAULT_OPENAI_MODEL, HTTP_CONNECT_TIMEOUT_SECONDS, HTTP_TIMEOUT_SECONDS
from ..models import TokenUsage
from .base import LLMClient, LLMResponse, OnChunkCallback, ToolCall
from .errors import LLMError, classify_response

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com"

#: OpenAI finish_reason → 统一 stop_reason（此前在流式/非流式两处各抄一份）。
OPENAI_FINISH_REASON_MAP = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "end_turn",
}

# Models that require `max_completion_tokens` and reject custom temperature.
_REASONING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5", "chatgpt-4o")


def uses_completion_tokens(model: str) -> bool:
    """推理系模型（o1/o3/o4/gpt-5 等）需用 max_completion_tokens 且不接受自定义温度。"""
    low = (model or "").lower()
    return any(low.startswith(p) for p in _REASONING_MODEL_PREFIXES)


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


# ---------------------------------------------------------------------------
# 多模态（G-3）：统一内部表示 → OpenAI 分格式
#
# 统一内部表示（与 anthropic.py 同一口径）：消息 content 可以是纯字符串，
# 也可以是多部件列表：
#   {"type": "text", "text": ...}
#   {"type": "image", "media_type": "image/png", "data": "<base64>"}
# OpenAI-compat 侧图片部件转成 data URL 形式的 image_url 部件。
# ---------------------------------------------------------------------------


def _part_to_openai(part: dict) -> dict:
    """把统一内部表示的一个部件转成 OpenAI content part。"""
    if part.get("type") == "image":
        media_type = part.get("media_type", "image/png")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{part.get('data', '')}"},
        }
    return {"type": "text", "text": str(part.get("text", ""))}


def _content_to_openai(content: Any) -> Any:
    """把统一 content（str 或部件列表）转成 OpenAI content。"""
    if isinstance(content, list):
        return [_part_to_openai(p) if isinstance(p, dict) else {"type": "text", "text": str(p)}
                for p in content]
    return content


def _build_openai_messages(messages: list[dict], system: str = "") -> list[dict]:
    """Convert unified message format to OpenAI's message format.

    多模态（G-3）：content 为部件列表时逐部件适配；连续 user 消息在此合并
    （与 anthropic.py 同口径——会话层把「图片消息 + 文本 prompt」拆成两条
    user 消息传入，这里并回一条，保证两协议上下文一致）。
    """
    # 注解显式化（G-3）：content 可为 str 或部件列表，推断会让 mypy 把本列表
    # 收窄成 list[dict[str, str]]，合并多部件 user 消息时误报。
    result: list[dict[str, Any]] = []
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

        converted = _content_to_openai(content)
        # 连续 user 消息合并为一条（跳过空文本部件）
        if role == "user" and result and result[-1]["role"] == "user":
            prev = result[-1]["content"]
            prev_parts = (
                [{"type": "text", "text": prev}] if isinstance(prev, str) else list(prev)
            )
            new_parts = (
                [{"type": "text", "text": converted}]
                if isinstance(converted, str)
                else list(converted)
            )
            merged = [*prev_parts, *[p for p in new_parts if p.get("text") != "" or p.get("type") != "text"]]
            result[-1]["content"] = merged
            continue

        result.append({"role": role, "content": converted})
    return result


class OpenAICompatClient(LLMClient):
    """OpenAI-compatible Chat Completions API client."""

    def __init__(self, api_key: str, base_url: str = "", model: str = DEFAULT_OPENAI_MODEL):
        super().__init__()  # initialises per-instance throttle state
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
        on_chunk: OnChunkCallback | None = None,
        on_activity: Any | None = None,
        on_thought: OnChunkCallback | None = None,
    ) -> LLMResponse:
        """OpenAI Chat Completions 实现（流式回调语义见 :class:`LLMClient.chat`）。"""
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
        }
        if uses_completion_tokens(self.model):
            # Reasoning models require the new parameter name and reject
            # sampling controls other than the default temperature.
            body["max_completion_tokens"] = max_tokens
        else:
            body["temperature"] = temperature
            body["max_tokens"] = max_tokens
        openai_tools = _convert_tools_to_openai(tools)
        if openai_tools:
            body["tools"] = openai_tools

        await self._throttle()

        if on_chunk is not None:
            body["stream"] = True
            # 缺陷 D：流式默认拿不到 usage——显式要求端点回传计量 chunk
            #（OpenAI 规范字段；不认识的兼容端点由降级逻辑兜底，见下）。
            body["stream_options"] = {"include_usage": True}
            return await self._chat_streaming(url, headers, body, on_chunk, on_activity, on_thought)

        resp = await self._client.post(url, headers=headers, json=body)

        if resp.status_code != 200:
            raise classify_response(resp.status_code, dict(resp.headers), resp.text)

        data = resp.json()
        return self._parse_response(data)

    async def _chat_streaming(
        self,
        url: str,
        headers: dict,
        body: dict,
        on_chunk: OnChunkCallback,
        on_activity: Any | None = None,
        on_thought: OnChunkCallback | None = None,
    ) -> LLMResponse:
        """Stream the OpenAI-compatible response via SSE, calling on_chunk for text deltas.

        缺陷 D 兜底：个别兼容端点不认识 ``stream_options``（HTTP 400 且报文
        含该字样）——自动去掉该字段重发**一次**，只降一级，防死循环。
        """
        current_body = body
        for _ in range(2):  # 首发最多 + 一次去 stream_options 的降级重发
            try:
                return await self._chat_stream_once(
                    url, headers, current_body, on_chunk, on_activity, on_thought,
                )
            except LLMError as exc:
                already_degraded = current_body is not body
                if (
                    not already_degraded
                    and getattr(exc, "status_code", None) == 400
                    and "stream_options" in str(exc).lower()
                ):
                    current_body = {
                        k: v for k, v in body.items() if k != "stream_options"
                    }
                    continue
                raise
        raise LLMError("unreachable: streaming retry loop exited")

    async def _chat_stream_once(
        self,
        url: str,
        headers: dict,
        body: dict,
        on_chunk: OnChunkCallback,
        on_activity: Any | None = None,
        on_thought: OnChunkCallback | None = None,
    ) -> LLMResponse:
        """Issue one streaming request and consume its SSE frames."""
        content_text = ""
        tool_calls_by_index: dict[int, dict] = {}
        stop_reason = "end_turn"
        usage = TokenUsage()

        async with self._client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                await resp.aread()
                raise classify_response(resp.status_code, dict(resp.headers), resp.text)

            async for line in resp.aiter_lines():
                if on_activity is not None:
                    on_activity()
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

                # R17 思考链（阶段4）：reasoning 模型的思考增量此前未读取。
                # 兼容两类字段名（deepseek 系 reasoning_content / 部分端点
                # reason_content）；走独立回调，绝不混入正文 content_text。
                if on_thought is not None:
                    thought = delta.get("reasoning_content") or delta.get("reason_content")
                    if thought:
                        result = on_thought(str(thought))
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
                    stop_reason = OPENAI_FINISH_REASON_MAP.get(finish, finish)

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
        stop_reason = OPENAI_FINISH_REASON_MAP.get(finish_reason, finish_reason)

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
        """释放底层 httpx 连接池。"""
        await self._client.aclose()
