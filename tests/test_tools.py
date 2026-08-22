"""Tests for research_assistant.tools — built-in tool implementations."""

import os

import pytest

from research_assistant.tools.bash import run_bash
from research_assistant.tools.file_ops import (
    edit_file,
    glob_files,
    grep_search,
    read_file,
    write_file,
)
from research_assistant.tools.registry import TOOL_DEFINITIONS, ToolRegistry


class TestReadFile:
    @pytest.mark.asyncio
    async def test_read_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        result = await read_file(str(f))
        assert "1\tline1" in result
        assert "2\tline2" in result

    @pytest.mark.asyncio
    async def test_read_nonexistent(self):
        result = await read_file("/nonexistent/path/file.txt")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_read_with_offset(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("\n".join(f"line{i}" for i in range(10)))
        result = await read_file(str(f), offset=5, limit=3)
        assert "6\tline5" in result
        assert "line0" not in result

    @pytest.mark.asyncio
    async def test_read_directory_fails(self, tmp_path):
        result = await read_file(str(tmp_path))
        assert "Error" in result


class TestWriteFile:
    @pytest.mark.asyncio
    async def test_write_new_file(self, tmp_path):
        f = tmp_path / "new.txt"
        result = await write_file(str(f), "hello world")
        assert "Successfully" in result
        assert f.read_text() == "hello world"

    @pytest.mark.asyncio
    async def test_write_creates_parents(self, tmp_path):
        f = tmp_path / "a" / "b" / "c.txt"
        result = await write_file(str(f), "nested")
        assert "Successfully" in result
        assert f.read_text() == "nested"


class TestEditFile:
    @pytest.mark.asyncio
    async def test_edit_replaces_string(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world foo bar")
        result = await edit_file(str(f), "foo", "baz")
        assert "Successfully" in result
        assert f.read_text() == "hello world baz bar"

    @pytest.mark.asyncio
    async def test_edit_nonexistent_file(self):
        result = await edit_file("/nonexistent.txt", "a", "b")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_edit_string_not_found(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = await edit_file(str(f), "xyz", "abc")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_edit_duplicate_string(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("aa aa aa")
        result = await edit_file(str(f), "aa", "bb")
        assert "appears 3 times" in result


class TestGlobFiles:
    @pytest.mark.asyncio
    async def test_glob_finds_files(self, tmp_path):
        (tmp_path / "a.py").touch()
        (tmp_path / "b.py").touch()
        (tmp_path / "c.txt").touch()
        result = await glob_files("*.py", str(tmp_path))
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result

    @pytest.mark.asyncio
    async def test_glob_no_matches(self, tmp_path):
        result = await glob_files("*.xyz", str(tmp_path))
        assert "No files" in result


class TestGrepSearch:
    @pytest.mark.asyncio
    async def test_grep_finds_pattern(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("def hello():\n    pass\ndef world():\n    pass\n")
        result = await grep_search("def \\w+", str(tmp_path), glob="*.py")
        assert "def hello" in result
        assert "def world" in result

    @pytest.mark.asyncio
    async def test_grep_no_matches(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = await grep_search("xyz123", str(tmp_path))
        assert "No matches" in result


class TestRunBash:
    @pytest.mark.asyncio
    async def test_simple_command(self, tmp_path):
        result = await run_bash("echo hello", cwd=str(tmp_path))
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_command_timeout(self, tmp_path):
        if os.name == "nt":
            result = await run_bash("ping -n 10 127.0.0.1", timeout=1, cwd=str(tmp_path))
        else:
            result = await run_bash("sleep 10", timeout=1, cwd=str(tmp_path))
        assert "timed out" in result

    @pytest.mark.asyncio
    async def test_command_failure(self, tmp_path):
        result = await run_bash("exit 1", cwd=str(tmp_path))
        assert "Exit code: 1" in result


class TestToolRegistry:
    def test_tool_definitions_exist(self):
        assert len(TOOL_DEFINITIONS) >= 7

    def test_all_tools_have_required_fields(self):
        for td in TOOL_DEFINITIONS:
            assert "name" in td
            assert "description" in td
            assert "parameters" in td

    def test_registry_get_schemas(self):
        registry = ToolRegistry()
        schemas = registry.get_schemas()
        assert len(schemas) >= 7

    @pytest.mark.asyncio
    async def test_registry_execute_unknown_tool(self):
        registry = ToolRegistry()
        result = await registry.execute("nonexistent_tool", {})
        assert "Unknown tool" in result

    @pytest.mark.asyncio
    async def test_registry_execute_read(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        registry = ToolRegistry(work_dir=str(tmp_path))
        result = await registry.execute("read_file", {"file_path": str(f)})
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_registry_execute_run_python(self, tmp_path):
        registry = ToolRegistry(work_dir=str(tmp_path))
        result = await registry.execute("run_python", {"code": "print(1+2)"})
        assert "3" in result

    def test_run_python_in_definitions(self):
        names = [td["name"] for td in TOOL_DEFINITIONS]
        assert "run_python" in names
