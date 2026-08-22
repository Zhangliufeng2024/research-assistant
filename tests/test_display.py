"""Tests for research_assistant.display — tool and status formatting."""

from research_assistant.display import (
    format_status_line,
    format_tool_result_tag,
    format_tool_start,
)
from research_assistant.models import TokenUsage


class TestFormatToolStart:
    def test_write_file(self):
        result = format_tool_start("write_file", {"file_path": "drafts/v1.docx"})
        assert "Write" in result
        assert "v1.docx" in result

    def test_read_file(self):
        result = format_tool_start("read_file", {"file_path": "data/input.csv"})
        assert "Read" in result
        assert "input.csv" in result

    def test_edit_file(self):
        result = format_tool_start("edit_file", {"file_path": "refs.bib"})
        assert "Edit" in result
        assert "refs.bib" in result

    def test_bash_truncation(self):
        long_cmd = "pdflatex -interaction=nonstopmode -output-directory=final manuscript.tex" + " " * 100
        result = format_tool_start("bash", {"command": long_cmd})
        assert "Bash" in result
        assert "..." in result
        assert len(result) < 200

    def test_bash_short(self):
        result = format_tool_start("bash", {"command": "echo hello"})
        assert "Bash" in result
        assert "echo hello" in result
        assert "..." not in result

    def test_run_python_single_line(self):
        result = format_tool_start("run_python", {"code": "print('hi')"})
        assert "Python" in result
        assert "1 line" in result

    def test_run_python_multi_lines(self):
        code = "x = 1\ny = 2\nprint(x + y)"
        result = format_tool_start("run_python", {"code": code})
        assert "Python" in result
        assert "3 lines" in result

    def test_glob(self):
        result = format_tool_start("glob_files", {"pattern": "*.py"})
        assert "Glob" in result
        assert "*.py" in result

    def test_grep(self):
        result = format_tool_start("grep_search", {"pattern": "def main"})
        assert "Grep" in result
        assert "def main" in result

    def test_unknown_tool(self):
        result = format_tool_start("custom_tool", {"arg": "value"})
        assert "custom_tool" in result


class TestFormatToolResultTag:
    def test_success(self):
        assert "[OK]" in format_tool_result_tag("File written successfully")

    def test_error(self):
        assert "[ERR]" in format_tool_result_tag("Error: file not found")

    def test_exit_code_error(self):
        assert "[ERR]" in format_tool_result_tag("Exit code: 1\nsome output")


class TestFormatStatusLine:
    def test_basic(self):
        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        result = format_status_line(3, 12.5, usage)
        assert "Turn 3" in result
        assert "12s" in result or "13s" in result
        assert "1,500" in result
        assert "tokens" in result

    def test_zero_tokens(self):
        usage = TokenUsage()
        result = format_status_line(1, 0.0, usage)
        assert "Turn 1" in result
        assert "0 tokens" in result

    def test_large_token_count(self):
        usage = TokenUsage(input_tokens=50000, output_tokens=25000)
        result = format_status_line(10, 120.0, usage)
        assert "75,000" in result
