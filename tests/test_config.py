"""Tests for research_assistant.config."""

import pytest

from research_assistant.config import build_llm_client, resolve_model


class TestResolveModel:
    def test_explicit_model(self):
        assert resolve_model("custom-model") == "custom-model"

    def test_env_override_llm_model(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "env-model")
        assert resolve_model() == "env-model"

    def test_default(self, monkeypatch):
        monkeypatch.delenv("LLM_MODEL", raising=False)
        assert resolve_model() == "claude-sonnet-4-6"

    def test_explicit_takes_priority_over_env(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "env-model")
        assert resolve_model("explicit") == "explicit"


class TestBuildLlmClient:
    def test_creates_anthropic_client(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-ant-test-key")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        client = build_llm_client()
        from research_assistant.llm.anthropic import AnthropicClient
        assert isinstance(client, AnthropicClient)

    def test_creates_openai_client(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-test-openai-key")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        client = build_llm_client()
        from research_assistant.llm.openai_compat import OpenAICompatClient
        assert isinstance(client, OpenAICompatClient)

    def test_explicit_provider_override(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-ant-test-key")
        client = build_llm_client(provider="openai")
        from research_assistant.llm.openai_compat import OpenAICompatClient
        assert isinstance(client, OpenAICompatClient)

    def test_raises_without_key(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with pytest.raises(ValueError, match="No LLM API key"):
            build_llm_client()


# ---------------------------------------------------------------------------
# R12 P1：任务模式系统提示注入执行契约
# ---------------------------------------------------------------------------

class TestBuildSystemInstructionsContract:
    def test_frozen_addendum_appended(self, tmp_path, monkeypatch):
        import sys

        from research_assistant.config import build_system_instructions

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        text = build_system_instructions(tmp_path, "20260823_demo")
        assert "WORKING DIRECTORY" in text
        assert "run_script" in text
        assert "sys.executable" in text

    def test_dev_addendum_is_placeholder(self, tmp_path, monkeypatch):
        import sys

        from research_assistant.config import build_system_instructions

        monkeypatch.setattr(sys, "frozen", False, raising=False)
        text = build_system_instructions(tmp_path, "20260823_demo")
        assert "run_script" not in text
