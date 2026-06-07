"""Tests for research_assistant.core."""

import os
import zipfile
from pathlib import Path

from research_assistant.core import (
    get_api_key,
    load_system_instructions,
    ensure_output_folder,
    get_image_extensions,
    get_manuscript_extensions,
    get_source_extensions,
    get_data_extensions,
    get_data_files,
    extract_images_from_docx,
    process_data_files,
    create_data_context_message,
    ensure_dotenv_loaded,
)
import pytest


class TestGetApiKey:
    def test_returns_explicit_key(self):
        assert get_api_key("sk-test") == "sk-test"

    def test_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-env")
        assert get_api_key() == "sk-env"

    def test_raises_if_missing(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with pytest.raises(ValueError, match="No API key"):
            get_api_key()

    def test_explicit_key_takes_priority(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-env")
        assert get_api_key("sk-explicit") == "sk-explicit"


class TestLoadSystemInstructions:
    def test_loads_from_file(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        writer_file = claude_dir / "WRITER.md"
        writer_file.write_text("Custom instructions here")
        assert load_system_instructions(tmp_path) == "Custom instructions here"

    def test_fallback_when_missing(self, tmp_path):
        result = load_system_instructions(tmp_path)
        assert "scientific writing assistant" in result


class TestEnsureOutputFolder:
    def test_creates_default_folder(self, tmp_path):
        result = ensure_output_folder(tmp_path)
        assert result == tmp_path / "writing_outputs"
        assert result.exists()

    def test_custom_dir(self, tmp_path):
        custom = tmp_path / "custom_output"
        result = ensure_output_folder(tmp_path, str(custom))
        assert result == custom
        assert result.exists()


class TestExtensionSets:
    def test_image_extensions(self):
        exts = get_image_extensions()
        assert ".png" in exts
        assert ".jpg" in exts
        assert ".svg" in exts

    def test_manuscript_extensions(self):
        assert ".tex" in get_manuscript_extensions()

    def test_source_extensions(self):
        exts = get_source_extensions()
        assert ".md" in exts
        assert ".docx" in exts

    def test_data_extensions(self):
        exts = get_data_extensions()
        assert ".csv" in exts
        assert ".json" in exts
        assert ".xlsx" in exts


class TestGetDataFiles:
    def test_explicit_list(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b")
        result = get_data_files(tmp_path, [str(f)])
        assert len(result) == 1

    def test_from_data_folder(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "file.csv").write_text("1,2")
        (data_dir / "file.json").write_text("{}")
        result = get_data_files(tmp_path)
        assert len(result) == 2

    def test_empty_data_folder(self, tmp_path):
        assert get_data_files(tmp_path) == []

    def test_no_data_folder(self, tmp_path):
        assert get_data_files(tmp_path) == []


class TestExtractImagesFromDocx:
    def _make_docx_with_image(self, path: Path) -> Path:
        """Create a minimal .docx (zip) with a fake image in word/media/."""
        docx_path = path / "test.docx"
        with zipfile.ZipFile(docx_path, "w") as zf:
            zf.writestr("word/media/image1.png", b"\x89PNG fake")
            zf.writestr("word/document.xml", "<document/>")
        return docx_path

    def test_extracts_images(self, tmp_path):
        docx = self._make_docx_with_image(tmp_path)
        figures_dir = tmp_path / "figures"
        figures_dir.mkdir()
        result = extract_images_from_docx(docx, figures_dir)
        assert len(result) == 1
        assert result[0]["name"] == "image1.png"
        assert (figures_dir / "image1.png").exists()

    def test_invalid_docx(self, tmp_path):
        bad_file = tmp_path / "bad.docx"
        bad_file.write_text("not a zip")
        figures_dir = tmp_path / "figures"
        figures_dir.mkdir()
        result = extract_images_from_docx(bad_file, figures_dir)
        assert result == []


class TestProcessDataFiles:
    def test_routes_files_correctly(self, tmp_path):
        paper_dir = tmp_path / "paper"
        paper_dir.mkdir()

        tex_file = tmp_path / "draft.tex"
        tex_file.write_text(r"\documentclass{article}")
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a,b")
        png_file = tmp_path / "fig.png"
        png_file.write_bytes(b"png data")
        md_file = tmp_path / "notes.md"
        md_file.write_text("notes")

        files = [tex_file, csv_file, png_file, md_file]
        result = process_data_files(tmp_path, files, str(paper_dir))

        assert len(result["manuscript_files"]) == 1
        assert len(result["data_files"]) == 1
        assert len(result["image_files"]) == 1
        assert len(result["source_files"]) == 1
        assert (paper_dir / "drafts" / "draft.tex").exists()
        assert (paper_dir / "data" / "data.csv").exists()
        assert (paper_dir / "figures" / "fig.png").exists()
        assert (paper_dir / "sources" / "notes.md").exists()

    def test_no_files(self, tmp_path):
        assert process_data_files(tmp_path, [], str(tmp_path)) is None

    def test_delete_originals_false(self, tmp_path):
        paper_dir = tmp_path / "paper"
        paper_dir.mkdir()
        f = tmp_path / "keep_me.csv"
        f.write_text("data")
        process_data_files(tmp_path, [f], str(paper_dir), delete_originals=False)
        assert f.exists()

    def test_delete_originals_true(self, tmp_path):
        paper_dir = tmp_path / "paper"
        paper_dir.mkdir()
        f = tmp_path / "delete_me.csv"
        f.write_text("data")
        process_data_files(tmp_path, [f], str(paper_dir), delete_originals=True)
        assert not f.exists()


class TestCreateDataContextMessage:
    def test_none_returns_empty(self):
        assert create_data_context_message(None) == ""

    def test_empty_files(self):
        assert create_data_context_message({"all_files": []}) == ""

    def test_includes_data_files(self):
        info = {
            "all_files": [{"name": "data.csv", "type": "data"}],
            "data_files": [{"name": "data.csv", "path": "/path/data.csv"}],
            "image_files": [],
            "manuscript_files": [],
            "source_files": [],
        }
        msg = create_data_context_message(info)
        assert "data.csv" in msg
        assert "DATA FILES AVAILABLE" in msg

    def test_manuscript_triggers_editing_mode(self):
        info = {
            "all_files": [{"name": "draft.tex", "type": "manuscript"}],
            "data_files": [],
            "image_files": [],
            "manuscript_files": [{"name": "draft.tex", "path": "/p", "extension": ".tex"}],
            "source_files": [],
        }
        msg = create_data_context_message(info)
        assert "EDITING MODE" in msg
