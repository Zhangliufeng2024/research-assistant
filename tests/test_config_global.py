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
    def test_managed_keys_global_wins_workspace_overrides_rest(self, tmp_path, isolated_appdata, monkeypatch):
        """托管四键以全局为终局裁决；非托管键仍是工作区覆盖层获胜（缺陷 G）。"""
        global_env = app_config_env_path()
        global_env.parent.mkdir(parents=True, exist_ok=True)
        global_env.write_text(
            "LLM_API_KEY=sk-global\nLLM_MODEL=global-model\nRA_NOTE=global-note\n",
            encoding="utf-8",
        )
        (tmp_path / ".env").write_text(
            "LLM_MODEL=ws-model\nRA_NOTE=ws-note\n",
            encoding="utf-8",
        )
        for k in ("LLM_API_KEY", "LLM_MODEL", "RA_NOTE"):
            monkeypatch.delenv(k, raising=False)

        load_project_env(tmp_path)

        assert os.environ["LLM_API_KEY"] == "sk-global"
        assert os.environ["LLM_MODEL"] == "global-model"  # 托管键：全局终局裁决
        assert os.environ["RA_NOTE"] == "ws-note"  # 非托管键：工作区覆盖层获胜

    def test_empty_global_managed_key_falls_back_to_workspace(self, tmp_path, isolated_appdata, monkeypatch):
        """全局文件里托管键为空值时不强制：工作区值照常生效。"""
        global_env = app_config_env_path()
        global_env.parent.mkdir(parents=True, exist_ok=True)
        global_env.write_text("LLM_MODEL=\n", encoding="utf-8")
        (tmp_path / ".env").write_text("LLM_MODEL=ws-fallback\n", encoding="utf-8")
        monkeypatch.delenv("LLM_MODEL", raising=False)

        load_project_env(tmp_path)

        assert os.environ["LLM_MODEL"] == "ws-fallback"

    def test_stale_workspace_key_cannot_override_global(self, tmp_path, isolated_appdata, monkeypatch):
        """核心场景：设置页写入的新全局 Key 不被工作区残留旧 Key 压掉。"""
        global_env = app_config_env_path()
        global_env.parent.mkdir(parents=True, exist_ok=True)
        global_env.write_text("LLM_API_KEY=sk-new-global\n", encoding="utf-8")
        (tmp_path / ".env").write_text("LLM_API_KEY=sk-old-workspace\n", encoding="utf-8")
        monkeypatch.delenv("LLM_API_KEY", raising=False)

        load_project_env(tmp_path)

        assert os.environ["LLM_API_KEY"] == "sk-new-global"

    def test_workspace_only_config_still_works(self, tmp_path, isolated_appdata, monkeypatch):
        (tmp_path / ".env").write_text("LLM_API_KEY=sk-ws-only\n", encoding="utf-8")
        monkeypatch.delenv("LLM_API_KEY", raising=False)

        load_project_env(tmp_path)

        assert os.environ["LLM_API_KEY"] == "sk-ws-only"


class TestMigrationClearsWorkspaceResidue:
    def test_migration_removes_managed_keys_and_backs_up(self, tmp_path, isolated_appdata):
        (tmp_path / ".env").write_text(
            "LLM_API_KEY=sk-old\nLLM_MODEL=old-model\nOTHER_KEY=stay\n",
            encoding="utf-8",
        )

        ensure_global_config(tmp_path)

        text = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "LLM_API_KEY" not in text  # 残留已清除，杜绝旧 Key 复活
        assert "LLM_MODEL" not in text
        assert "OTHER_KEY=stay" in text  # 非托管键不动
        backup = tmp_path / ".env.ra-migration.bak"
        assert backup.is_file()  # 首次迁移留底
        assert "sk-old" in backup.read_text(encoding="utf-8")

    def test_no_backup_when_nothing_to_migrate(self, tmp_path, isolated_appdata):
        (tmp_path / ".env").write_text("OTHER_KEY=stay\n", encoding="utf-8")

        ensure_global_config(tmp_path)

        assert not (tmp_path / ".env.ra-migration.bak").exists()
        assert "OTHER_KEY=stay" in (tmp_path / ".env").read_text(encoding="utf-8")
