"""Tests for research_assistant.orchestrator — plan parsing and data models."""

import pytest

from research_assistant.orchestrator import (
    AgentResult,
    FigurePlan,
    OrchestrationPlan,
    SectionPlan,
    _extract_json_object,
    _parse_plan,
    _sanitize_filename,
)


class TestExtractJsonObject:
    def test_simple_object(self):
        assert _extract_json_object('{"key": "value"}') == '{"key": "value"}'

    def test_nested_braces(self):
        text = '{"a": {"b": 1}}'
        assert _extract_json_object(text) == text

    def test_text_before_and_after(self):
        text = 'Here is the plan: {"key": 1} and some trailing text'
        assert _extract_json_object(text) == '{"key": 1}'

    def test_string_with_braces(self):
        text = '{"msg": "hello {world}"}'
        assert _extract_json_object(text) == text

    def test_no_json(self):
        assert _extract_json_object("no json here") == ""

    def test_code_fence_wrapping(self):
        text = '```json\n{"key": "value"}\n```'
        result = _extract_json_object(text)
        assert result == '{"key": "value"}'


class TestParsePlan:
    def test_minimal_plan(self):
        raw = '{"paper_title": "Test", "sections": [], "figures": []}'
        plan = _parse_plan(raw)
        assert plan.paper_title == "Test"
        assert plan.sections == []
        assert plan.figures == []

    def test_full_plan(self):
        raw = '''{
            "paper_title": "Quantum Computing Survey",
            "paper_type": "literature_review",
            "venue": "Nature",
            "sections": [
                {
                    "name": "introduction",
                    "title": "Introduction",
                    "description": "Overview",
                    "estimated_words": 800,
                    "search_queries": ["quantum computing review"]
                }
            ],
            "figures": [
                {
                    "name": "graphical_abstract",
                    "description": "Overview diagram",
                    "type": "schematic",
                    "filename": "graphical_abstract.png"
                }
            ],
            "total_estimated_words": 5000,
            "citation_target": 40
        }'''
        plan = _parse_plan(raw)
        assert plan.paper_title == "Quantum Computing Survey"
        assert plan.paper_type == "literature_review"
        assert plan.venue == "Nature"
        assert len(plan.sections) == 1
        assert plan.sections[0].name == "introduction"
        assert len(plan.figures) == 1
        assert plan.total_estimated_words == 5000
        assert plan.citation_target == 40

    def test_with_markdown_wrapper(self):
        raw = 'Here is the plan:\n```json\n{"paper_title": "X"}\n```\nDone.'
        plan = _parse_plan(raw)
        assert plan.paper_title == "X"

    def test_missing_json_raises(self):
        with pytest.raises(ValueError, match="Could not find JSON"):
            _parse_plan("no json here at all")

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            _parse_plan("{invalid json content}")


class TestDataModels:
    def test_section_plan_defaults(self):
        s = SectionPlan(name="intro", title="Introduction", description="desc")
        assert s.estimated_words == 500
        assert s.search_queries == []

    def test_figure_plan_defaults(self):
        f = FigurePlan(name="fig1", description="a figure")
        assert f.type == "schematic"
        assert f.filename == ""

    def test_agent_result_defaults(self):
        r = AgentResult(agent_id="test", agent_role="Test Agent", success=True)
        assert r.text_output == ""
        assert r.files_written == []
        assert r.error is None

    def test_orchestration_plan_defaults(self):
        p = OrchestrationPlan()
        assert p.paper_title == ""
        assert p.sections == []
        assert p.citation_target == 30


class TestSanitizeFilename:
    def test_normal_name(self):
        assert _sanitize_filename("figure.png") == "figure.png"

    def test_strips_directory(self):
        assert _sanitize_filename("../../../etc/passwd") == "passwd"

    def test_strips_backslash_directory(self):
        result = _sanitize_filename("..\\..\\secret.txt")
        assert ".." not in result
        assert result.endswith("secret.txt")

    def test_replaces_special_chars(self):
        result = _sanitize_filename("file name (1).png")
        assert "/" not in result
        assert " " not in result

    def test_empty_string_returns_default(self):
        assert _sanitize_filename("") == "unnamed"

    def test_custom_default(self):
        assert _sanitize_filename("", default="fallback.png") == "fallback.png"

    def test_dots_only(self):
        result = _sanitize_filename("...")
        assert result == "..."
