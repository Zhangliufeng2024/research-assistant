"""Factory for creating LLM clients based on configuration."""

import os

from ..constants import DEFAULT_ANTHROPIC_MODEL, DEFAULT_OPENAI_MODEL
from .anthropic import AnthropicClient
from .base import LLMClient
from .fallback import FallbackLLMClient
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


def _build_client(
    *, api_key: str, base_url: str, provider: str, model: str,
) -> LLMClient:
    if provider == "anthropic":
        return AnthropicClient(
            api_key=api_key, base_url=base_url,
            model=model or DEFAULT_ANTHROPIC_MODEL,
        )
    return OpenAICompatClient(
        api_key=api_key, base_url=base_url,
        model=model or DEFAULT_OPENAI_MODEL,
    )


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

    A+ 阶段 5 / G-5：``RA_MODEL_FALLBACK`` 提供有序备选后返回
    :class:`FallbackLLMClient`，消除"主模型不可用即整个任务失败"的单点。

        RA_MODEL_FALLBACK = "openai:gpt-4o,anthropic:claude-sonnet-5"

    语法：逗号分隔，每项 ``provider:model``（推荐，显式无歧义）或裸模型名
    （provider 按 key/URL 推断，与主项同一套规则）。备选与主项共用同一把
    API key 与 base_url——跨 provider 混用时 key 也通常同源（聚合网关）。
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
        provider or os.getenv("LLM_PROVIDER") or "",
        url,
    )
    mdl = model or os.getenv("LLM_MODEL") or ""

    primary = _build_client(api_key=key, base_url=url, provider=prov, model=mdl)

    fallback_spec = (os.getenv("RA_MODEL_FALLBACK") or "").strip()
    if not fallback_spec:
        return primary

    # primary.model：LLMClient 基类未声明该属性（FallbackLLMClient 以 property
    # 提供），故用 getattr 兜底；具体客户端均在 __init__ 里设置 self.model。
    labels = [f"{prov}:{getattr(primary, 'model', '') or mdl or 'default'}"]
    clients: list[LLMClient] = [primary]
    for raw in fallback_spec.split(","):
        spec = raw.strip()
        if not spec:
            continue
        if ":" in spec:
            fb_provider, _, fb_model = spec.partition(":")
        else:
            fb_provider, fb_model = prov, spec
        clients.append(_build_client(
            api_key=key, base_url=url,
            provider=fb_provider.strip().lower(), model=fb_model.strip(),
        ))
        labels.append(f"{fb_provider.strip().lower()}:{fb_model.strip()}")
    return FallbackLLMClient(clients, labels=labels)
