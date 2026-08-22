"""Tests for research_assistant.models."""

import json
from datetime import datetime

from research_assistant.models import (
    PaperFiles,
    PaperMetadata,
    PaperResult,
    ProgressUpdate,
    TextUpdate,
    TokenUsage,
)


class TestProgressUpdate:
    def test_default_values(self):
        update = ProgressUpdate()
        assert update.type == "progress"
        assert update.stage == "initialization"
        assert update.message == ""
        assert update.details is None

    def test_timestamp_is_utc(self):
        update = ProgressUpdate()
        assert update.timestamp.endswith("Z")

    def test_to_dict_preserves_none_details(self):
        update = ProgressUpdate(message="test")
        d = update.to_dict()
        assert "details" in d
        assert d["details"] is None

    def test_to_dict_with_details(self):
        update = ProgressUpdate(message="test", details={"tool": "Bash"})
        d = update.to_dict()
        assert d["details"]["tool"] == "Bash"

    def test_serializable_as_json(self):
        update = ProgressUpdate(message="compiling", stage="compilation")
        s = json.dumps(update.to_dict())
        assert "compiling" in s


class TestTextUpdate:
    def test_default_values(self):
        u = TextUpdate()
        assert u.type == "text"
        assert u.content == ""

    def test_to_dict(self):
        u = TextUpdate(content="hello")
        d = u.to_dict()
        assert d == {"type": "text", "content": "hello"}


class TestPaperMetadata:
    def test_defaults(self):
        m = PaperMetadata()
        assert m.title is None
        assert m.topic == ""
        assert m.word_count is None

    def test_timestamp_format(self):
        m = PaperMetadata()
        assert m.created_at.endswith("Z")
        dt = datetime.fromisoformat(m.created_at.replace("Z", "+00:00"))
        assert dt.tzinfo is not None or m.created_at.endswith("Z")


class TestTokenUsage:
    def test_total_tokens(self):
        t = TokenUsage(input_tokens=100, output_tokens=50)
        assert t.total_tokens == 150

    def test_to_dict_includes_total(self):
        t = TokenUsage(input_tokens=10, output_tokens=20)
        d = t.to_dict()
        assert d["total_tokens"] == 30
        assert d["input_tokens"] == 10

    def test_zero_defaults(self):
        t = TokenUsage()
        assert t.total_tokens == 0


class TestPaperFiles:
    def test_defaults_are_empty(self):
        f = PaperFiles()
        assert f.pdf_final is None
        assert f.figures == []
        assert f.data == []
        assert f.docx_final is None
        assert f.docx_drafts == []

    def test_mutable_defaults_are_independent(self):
        f1 = PaperFiles()
        f2 = PaperFiles()
        f1.figures.append("fig.png")
        assert f2.figures == []

    def test_docx_drafts_independent(self):
        f1 = PaperFiles()
        f2 = PaperFiles()
        f1.docx_drafts.append("v1.docx")
        assert f2.docx_drafts == []


class TestPaperResult:
    def test_default_status(self):
        r = PaperResult()
        assert r.status == "success"
        assert r.compilation_success is False

    def test_to_dict_removes_none_token_usage(self):
        r = PaperResult()
        d = r.to_dict()
        assert "token_usage" not in d

    def test_to_dict_includes_token_usage(self):
        r = PaperResult(token_usage=TokenUsage(input_tokens=5, output_tokens=3))
        d = r.to_dict()
        assert d["token_usage"]["total_tokens"] == 8

    def test_nested_objects_are_dicts(self):
        r = PaperResult()
        d = r.to_dict()
        assert isinstance(d["metadata"], dict)
        assert isinstance(d["files"], dict)
