"""Tests for research_assistant.tools.python_exec."""

import os

import pytest

from research_assistant.tools.python_exec import run_python


class TestRunPython:
    @pytest.mark.asyncio
    async def test_simple_code(self, tmp_path):
        result = await run_python("print('hello world')", cwd=str(tmp_path))
        assert "hello world" in result

    @pytest.mark.asyncio
    async def test_multiline_code(self, tmp_path):
        code = "x = 2\ny = 3\nprint(x + y)"
        result = await run_python(code, cwd=str(tmp_path))
        assert "5" in result

    @pytest.mark.asyncio
    async def test_syntax_error(self, tmp_path):
        result = await run_python("def foo(", cwd=str(tmp_path))
        assert "Exit code:" in result
        assert "SyntaxError" in result

    @pytest.mark.asyncio
    async def test_runtime_error(self, tmp_path):
        result = await run_python("1 / 0", cwd=str(tmp_path))
        assert "Exit code:" in result
        assert "ZeroDivisionError" in result

    @pytest.mark.asyncio
    async def test_timeout(self, tmp_path):
        result = await run_python("import time; time.sleep(10)", timeout=1, cwd=str(tmp_path))
        assert "timed out" in result

    @pytest.mark.asyncio
    async def test_import_stdlib(self, tmp_path):
        result = await run_python("import json; print(json.dumps({'a': 1}))", cwd=str(tmp_path))
        assert '"a": 1' in result

    @pytest.mark.asyncio
    async def test_file_creation(self, tmp_path):
        code = f"from pathlib import Path; Path(r'{tmp_path / 'output.txt'}').write_text('created')"
        await run_python(code, cwd=str(tmp_path))
        assert (tmp_path / "output.txt").read_text() == "created"

    @pytest.mark.asyncio
    async def test_temp_file_cleanup(self, tmp_path):
        await run_python("print('cleanup test')", cwd=str(tmp_path))
        leftover = [f for f in tmp_path.iterdir() if f.name.startswith("_ra_exec_")]
        assert leftover == []

    @pytest.mark.asyncio
    async def test_no_output_returns_placeholder(self, tmp_path):
        result = await run_python("x = 1", cwd=str(tmp_path))
        assert result == "(no output)"

    @pytest.mark.asyncio
    async def test_stderr_captured(self, tmp_path):
        code = "import sys; sys.stderr.write('warning\\n')"
        result = await run_python(code, cwd=str(tmp_path))
        assert "warning" in result

    @pytest.mark.asyncio
    async def test_cwd_is_respected(self, tmp_path):
        code = "import os; print(os.getcwd())"
        result = await run_python(code, cwd=str(tmp_path))
        assert str(tmp_path) in result.replace("/", os.sep).replace("\\", os.sep)

    @pytest.mark.asyncio
    async def test_exit_code_nonzero(self, tmp_path):
        result = await run_python("import sys; sys.exit(42)", cwd=str(tmp_path))
        assert "Exit code: 42" in result
