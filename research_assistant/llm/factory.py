"""Factory for creating LLM clients based on configuration."""

import os
from typing import Optional

from .base import LLMClient
from .anthropic import AnthropicClient
from .openai_compat import OpenAICompatClient
from ..constants import DEFAULT_ANTHROPIC_MODEL, DEFAULT_OPENAI_MODEL


def detect_provider(api_key: str, provider: str = "") -> str:
    """Detect the LLM provider from explicit setting or API key format."""
    if provider:
        return provider.lower()
    if api_key.startswith("sk-ant-"):
        return "anthropic"
    return "openai"


def create_llm_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
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

    prov = detect_provider(
        key,
        provider or os.getenv("LLM_PROVIDER", ""),
    )

    url = base_url or os.getenv("LLM_BASE_URL") or ""
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
