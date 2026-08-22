"""Tests for R8 global config layer (config.app_data_dir / ensure_global_config
/ load_project_env 的全局先行-工作区覆盖语义)."""

import os

from research_assistant.config import (
    app_config_env_path,
    ensure_global_config,
    load_project_env,
)


class TestEnsureGlobalConfig:
    def test_copies_llm_keys_up_from_workspace(self, tmp_path, isolated_appdata):
        (tmp_path / ".env").write_text(
            "LLM_API_KEY=sk-workspace-key-1\nLLM_MODEL=deepseek-chat\nOTHER_KEY=stay\n",
            encoding="utf-8",
        )

        out = ensure_global_config(tmp_path)

        assert out == app_config_env_path()
        text = out.read_text(encoding="utf-8")
        assert "LLM_API_KEY=sk-workspace-key-1" in text
        assert "LLM_MODEL=deepseek-chat" in text
        assert "OTHER_KEY" not in text  # 只上移托管四键

    def test_global_already_configured_untouched(self, tmp_path, isolated_appdata):
        global_env = app_config_env_path()
        global_env.parent.mkdir(parents=True, exist_ok=True)
        global_env.write_text("LLM_API_KEY=sk-global-1\n", encoding="utf-8")
        (tmp_path / ".env").write_text("LLM_API_KEY=sk-workspace-2\n", encoding="utf-8")

        ensure_global_config(tmp_path)

        assert "sk-global-1" in global_env.read_text(encoding="utf-8")
        assert "sk-workspace-2" not in global_env.read_text(encoding="utf-8")

    def test_no_workspace_config_noop(self, tmp_path, isolated_appdata):
        ensure_global_config(tmp_path)
        assert not app_config_env_path().exists()

    def test_idempotent_second_run(self, tmp_path, isolated_appdata):
        (tmp_path / ".env").write_text("LLM_API_KEY=sk-k\n", encoding="utf-8")
        ensure_global_config(tmp_path)
        first = app_config_env_path().read_text(encoding="utf-8")
        ensure_global_config(tmp_path)  # 全局已配置：不再追加
        assert app_config_env_path().read_text(encoding="utf-8") == first


class TestLoadProjectEnvLayering:
    def test_global_first_workspace_overrides(self, tmp_path, isolated_appdata, monkeypatch):
        global_env = app_config_env_path()
        global_env.parent.mkdir(parents=True, exist_ok=True)
        global_env.write_text("LLM_API_KEY=sk-global\nLLM_MODEL=global-model\n", encoding="utf-8")
        (tmp_path / ".env").write_text("LLM_MODEL=ws-model\n", encoding="utf-8")
        for k in ("LLM_API_KEY", "LLM_MODEL"):
            monkeypatch.delenv(k, raising=False)

        load_project_env(tmp_path)

        assert os.environ["LLM_API_KEY"] == "sk-global"
        assert os.environ["LLM_MODEL"] == "ws-model"  # 工作区覆盖层获胜

    def test_workspace_only_config_still_works(self, tmp_path, isolated_appdata, monkeypatch):
        (tmp_path / ".env").write_text("LLM_API_KEY=sk-ws-only\n", encoding="utf-8")
        monkeypatch.delenv("LLM_API_KEY", raising=False)

        load_project_env(tmp_path)

        assert os.environ["LLM_API_KEY"] == "sk-ws-only"
