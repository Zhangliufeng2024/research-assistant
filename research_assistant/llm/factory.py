"""Factory for creating LLM clients based on configuration."""

import os

from ..constants import DEFAULT_ANTHROPIC_MODEL, DEFAULT_OPENAI_MODEL
from .anthropic import AnthropicClient
from .base import LLMClient
from .openai_compat import OpenAICompatClient


def detect_provider(api_key: str, provider: str = "", base_url: str = "") -> str:
    """探测 LLM provider：显式设置 > Base URL > Key 前缀 > openai 兜底。

    Base URL 判定优先于 Key 前缀的动机：第三方 Anthropic 兼容网关签发的
    key 往往不是 sk-ant- 前缀（聚合代理自定义格式），但 URL 里带有
    anthropic 字样——按 URL 归类才能选对 Messages 协议；sk-ant- 前缀仅
    作为官方直连时的最后识别手段。
    """
    if provider:
        return provider.lower()
    if "anthropic" in (base_url or "").lower():
        return "anthropic"
    if api_key.startswith("sk-ant-"):
        return "anthropic"
    return "openai"


def create_llm_client(
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> LLMClient:
    """Create an LLM client from explicit params or environment variables.

    Environment variables (fallback when params are None):
        LLM_API_KEY — API key
        LLM_BASE_URL — base URL
        LLM_MODEL — model name
        LLM_PROVIDER — "anthropic" or "openai"
    """
    key = api_key or os.getenv("LLM_API_KEY") or ""
    if not key:
        raise ValueError(
            "No LLM API key found. Set LLM_API_KEY in .env"
        )

    # url 先于 provider 探测解析：探测需要参考 base_url（见 detect_provider）
    url = base_url or os.getenv("LLM_BASE_URL") or ""
    prov = detect_provider(
        key,
        provider or os.getenv("LLM_PROVIDER", ""),
        url,
    )
    mdl = model or os.getenv("LLM_MODEL") or ""

    if prov == "anthropic":
        return AnthropicClient(
            api_key=key,
            base_url=url,
            model=mdl or DEFAULT_ANTHROPIC_MODEL,
        )
    else:
        return OpenAICompatClient(
            api_key=key,
            base_url=url,
            model=mdl or DEFAULT_OPENAI_MODEL,
        )
