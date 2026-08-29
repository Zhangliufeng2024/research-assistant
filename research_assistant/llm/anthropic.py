"""Anthropic Messages API client using httpx."""

import asyncio
import json
import os
import re
import uuid
from typing import Any

import httpx

from ..constants import (
    ANTHROPIC_API_VERSION,
    DEFAULT_ANTHROPIC_MODEL,
    HTTP_CONNECT_TIMEOUT_SECONDS,
    HTTP_TIMEOUT_SECONDS,
)
from ..models import TokenUsage
from .base import LLMClient, LLMResponse, OnChunkCallback, ToolCall
from .errors import (
    BadRequestError,
    OverloadedError,
    RateLimitError,
    ServerError,
    classify_response,
)

ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"

_CACHE_CONTROL = {"type": "ephemeral"}

# 流内 error 事件（HTTP 200 也可能出现，如中途 overloaded）→ 类型化异常映射。
# retryable 的判定口径：与 classify_response 对同类错误的分类保持一致。
_STREAM_ERROR_TYPES: dict[str, type] = {
    "overloaded_error": OverloadedError,
    "rate_limit_error": RateLimitError,
    "timeout_error": ServerError,
    "api_error": ServerError,
}


def _apply_cache_control(body: dict[str, Any]) -> None:
    """Mark cache breakpoints so the static prefix is billed at cache rates.

    Breakpoints cover (in cost order of impact):
      1. tools — identical every turn
      2. system — the long WRITER.md prompt, identical every turn
      3. last message — gives the growing conversation an incremental
         breakpoint, so each turn only re-processes the new tail.

    Sub-1024-token prefixes simply don't cache (no API error), so this is
    always safe to enable.
    """
    if body.get("tools"):
        body["tools"][-1] = {**body["tools"][-1], "cache_control": _CACHE_CONTROL}

    system = body.get("system")
    if isinstance(system, str):
        body["system"] = [{"type": "text", "text": system, "cache_control": _CACHE_CONTROL}]
    elif isinstance(system, list) and system:
        system[-1] = {**system[-1], "cache_control": _CACHE_CONTROL}

    messages = body.get("messages") or []
    if messages:
        content = messages[-1].get("content")
        if isinstance(content, str):
            messages[-1]["content"] = [
                {"type": "text", "text": content, "cache_control": _CACHE_CONTROL}
            ]
        elif isinstance(content, list) and content:
            content[-1] = {**content[-1], "cache_control": _CACHE_CONTROL}


def caching_enabled() -> bool:
    """Prompt caching is on by default; ANTHROPIC_PROMPT_CACHE=0 disables it."""
    return os.getenv("ANTHROPIC_PROMPT_CACHE", "true").lower() not in ("0", "false", "no", "off")


# ---------------------------------------------------------------------------
# 采样参数守卫（temperature / top_p / top_k）
#
# Anthropic 自 **Opus 4.7** 起弃用采样参数：传**非默认值**返回 HTTP 400。
# 该限制向后延续到 Opus 4.8 / Opus 5 / Sonnet 5 / Fable 5 / Mythos 5 及
# Mythos Preview。Haiku 4.5 是例外，仍接受（但 temperature 与 top_p 不可同时给）。
#
# 影响面：默认模型正是 claude-sonnet-5（constants.py），而 RunConfig 默认
# temperature=0.5、chat() 默认 0.7 —— 两者都是非默认值。若无条件下发，
# 新用户只填 API Key、不指定模型时**每一通请求都会 400**。
#
# ⚠️ 正则陷阱（2026-08 实测，勿改回按 `-4-` 结构匹配）：
# Claude 5 的 ID 丢掉了 minor 段（claude-opus-4-8 → claude-opus-5），
# 任何形如 /^claude-(opus|sonnet|haiku)-4-([7-9]|\d{2,})/ 的单一判断都会对
# 5.x 模型静默失配，于是照发 temperature、于是每条请求 400。必须按
# **主版本号**判断，并把 4.x 区间单独保留。
# ---------------------------------------------------------------------------

#: 任意家族、主版本 ≥5：claude-sonnet-5 / claude-opus-5 / claude-fable-5 / claude-mythos-5
_NO_SAMPLING_MAJOR_5_PLUS = re.compile(r"^claude-[a-z]+-(?:[5-9]|\d{2,})(?!\d)")
#: Opus/Sonnet/Haiku 4.x 中 4.7 及以后：claude-opus-4-7、claude-opus-4-8、…、claude-opus-4-10
_NO_SAMPLING_4X_47_PLUS = re.compile(r"^claude-(?:opus|sonnet|haiku)-4-(?:[7-9]|\d{2,})")
#: Mythos 预览版同样拒绝采样参数
_NO_SAMPLING_MYTHOS_PREVIEW = re.compile(r"^claude-mythos-preview")


def supports_sampling_params(model: str) -> bool:
    """Whether *model* accepts temperature / top_p / top_k.

    Returns ``False`` for models that reject non-default sampling parameters
    with HTTP 400 (Claude Opus 4.7+, every Claude 5 model, Mythos).

    判定原则：**未知即放行**。守卫的目的是修好已知会 400 的模型，绝不能
    让一个今天还能正常工作的 provider/模型因为守卫而失效。非 Claude 模型、
    无法识别的自定义 ID 一律返回 ``True``（保持既有行为）。
    """
    m = (model or "").strip().lower()
    if not m.startswith("claude-"):
        return True
    if _NO_SAMPLING_MYTHOS_PREVIEW.match(m):
        return False
    if _NO_SAMPLING_MAJOR_5_PLUS.match(m):
        return False
    if _NO_SAMPLING_4X_47_PLUS.match(m):
        return False
    return True


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


# ---------------------------------------------------------------------------
# 多模态（G-3）：统一内部表示 → Anthropic 分格式
#
# 统一内部表示：消息 content 可以是纯字符串，也可以是**多部件列表**：
#   {"type": "text", "text": ...}
#   {"type": "image", "media_type": "image/png", "data": "<base64>"}
# 各协议在消息构造层（而非调用方）完成分格式适配，调用方只面对统一表示。
# ---------------------------------------------------------------------------


def _part_to_anthropic(part: dict) -> dict:
    """把统一内部表示的一个部件转成 Anthropic content block。"""
    if part.get("type") == "image":
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": part.get("media_type", "image/png"),
                "data": part.get("data", ""),
            },
        }
    # text 部件与 Anthropic 原生格式一致，原样透传
    return {"type": "text", "text": str(part.get("text", ""))}


def _content_to_anthropic(content: Any) -> Any:
    """把统一 content（str 或部件列表）转成 Anthropic content。"""
    if isinstance(content, list):
        return [_part_to_anthropic(p) if isinstance(p, dict) else {"type": "text", "text": str(p)}
                for p in content]
    return content


def _build_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Convert unified message format to Anthropic's message format.

    Handles tool_result blocks by wrapping them in the Anthropic content format.
    多模态（G-3）：content 为部件列表时逐部件适配；连续 user 消息在此合并
    （Anthropic 要求角色交替，会话层把「图片消息 + 文本 prompt」拆成两条
    user 消息传入，这里负责并回一条）。
    """
    result: list[dict] = []
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

        # user（含多部件）：连续 user 消息合并为一条，跳过空文本部件
        converted = _content_to_anthropic(content)
        if (
            role == "user"
            and result
            and result[-1]["role"] == "user"
        ):
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



#: Anthropic stop_reason → 统一 stop_reason（此前在流式/非流式两处各抄一份）。
ANTHROPIC_STOP_REASON_MAP = {
    "end_turn": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "stop_sequence": "end_turn",
}

class AnthropicClient(LLMClient):
    """Anthropic Messages API client."""

    def __init__(self, api_key: str, base_url: str = "", model: str = DEFAULT_ANTHROPIC_MODEL,
                 enable_cache: bool | None = None):
        super().__init__()  # initialises per-instance throttle state
        self.api_key = api_key
        self.base_url = (base_url or ANTHROPIC_DEFAULT_BASE_URL).rstrip("/")
        self.model = model
        self.enable_cache = caching_enabled() if enable_cache is None else enable_cache
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
        """Anthropic Messages API 实现（流式回调语义见 :class:`LLMClient.chat`）。"""
        base = self.base_url
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        url = f"{base}/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }

        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": _build_anthropic_messages(messages),
        }
        # 采样参数（temperature/top_p/top_k）在 Opus 4.7+ 与 Claude 5 全系
        # 传非默认值即 400，必须按模型判断后再下发——切勿无条件发送。
        # 详见 supports_sampling_params 上方的说明与正则陷阱。
        if supports_sampling_params(self.model):
            body["temperature"] = temperature
        if system:
            body["system"] = system
        anthropic_tools = _convert_tools_to_anthropic(tools)
        if anthropic_tools:
            body["tools"] = anthropic_tools

        if self.enable_cache:
            _apply_cache_control(body)

        await self._throttle()

        if on_chunk is not None:
            body["stream"] = True
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
        """Stream the Anthropic response via SSE, calling on_chunk for text deltas."""
        content_text = ""
        tool_calls: list[ToolCall] = []
        stop_reason = "end_turn"
        usage = TokenUsage()

        current_tool_id = ""
        current_tool_name = ""
        current_tool_json = ""
        in_tool_block = False

        async with self._client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                await resp.aread()
                raise classify_response(resp.status_code, dict(resp.headers), resp.text)

            async for line in resp.aiter_lines():
                if on_activity is not None:
                    on_activity()
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if not data_str or data_str.strip() == "[DONE]":
                    continue
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")

                if etype == "message_start":
                    msg_usage = event.get("message", {}).get("usage", {})
                    usage.input_tokens = msg_usage.get("input_tokens", 0)
                    # 缓存计量（缺陷 E）：与非流式 _parse_response 的字段对齐，
                    # 否则流式调用在预算/成本口径里丢掉 cache 读写字量。
                    usage.cache_creation_input_tokens = msg_usage.get(
                        "cache_creation_input_tokens", 0)
                    usage.cache_read_input_tokens = msg_usage.get(
                        "cache_read_input_tokens", 0)

                elif etype == "error":
                    # 缺陷 C：HTTP 200 流内也可能收到 error 事件（最典型是
                    # 中途 overloaded_error）——旧实现落入 continue，半截文
                    # 被当成完整成功。这里显式抛类型化 LLMError，让上层重试
                    # 链接管（已发布的半截文由 agent 的重试语义标注处理）。
                    payload = event.get("error", {}) or {}
                    error_type = str(payload.get("type", ""))
                    message = str(payload.get("message", "")) or json.dumps(
                        event, ensure_ascii=False)
                    exc_cls = _STREAM_ERROR_TYPES.get(error_type, BadRequestError)
                    raise exc_cls(
                        f"Anthropic stream error ({error_type}): {message[:300]}",
                        provider_type=error_type,
                    )

                elif etype == "content_block_start":
                    block = event.get("content_block", {})
                    if block.get("type") == "tool_use":
                        in_tool_block = True
                        current_tool_id = block.get("id", str(uuid.uuid4()))
                        current_tool_name = block.get("name", "")
                        current_tool_json = ""
                    else:
                        in_tool_block = False

                elif etype == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            content_text += text
                            result = on_chunk(text)
                            if asyncio.iscoroutine(result):
                                await result
                    elif delta.get("type") == "input_json_delta":
                        current_tool_json += delta.get("partial_json", "")
                    elif delta.get("type") == "thinking_delta" and on_thought is not None:
                        # R17 思考链（阶段4）：此前 thinking block 被静默丢弃。
                        # 思考增量走独立回调——绝不混入 content_text（正文权威）。
                        thinking = delta.get("thinking", "")
                        if thinking:
                            result = on_thought(thinking)
                            if asyncio.iscoroutine(result):
                                await result

                elif etype == "content_block_stop":
                    if in_tool_block:
                        try:
                            args = json.loads(current_tool_json) if current_tool_json else {}
                        except json.JSONDecodeError:
                            args = {"raw": current_tool_json}
                        tool_calls.append(ToolCall(
                            id=current_tool_id,
                            name=current_tool_name,
                            arguments=args,
                        ))
                        in_tool_block = False

                elif etype == "message_delta":
                    delta = event.get("delta", {})
                    raw_stop = delta.get("stop_reason", "")
                    if raw_stop:
                        stop_reason = ANTHROPIC_STOP_REASON_MAP.get(raw_stop, raw_stop)
                    msg_usage = event.get("usage", {})
                    usage.output_tokens = msg_usage.get("output_tokens", 0)

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
        )

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

        raw_stop = data.get("stop_reason", "end_turn")
        stop_reason = ANTHROPIC_STOP_REASON_MAP.get(raw_stop, raw_stop)

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
        """释放底层 httpx 连接池。"""
        await self._client.aclose()
