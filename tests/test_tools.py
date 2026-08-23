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


# ---------------------------------------------------------------------------
# R12 P1：run_python 工具描述讲清打包态执行方式（A6）
# ---------------------------------------------------------------------------

class TestRunPythonDescription:
    def test_description_documents_run_script_and_frozen_semantics(self):
        td = next(t for t in TOOL_DEFINITIONS if t["name"] == "run_python")
        desc = td["description"]
        assert "run_script" in desc
        assert "进程内" in desc or "in-process" in desc


# ---------------------------------------------------------------------------
# R12 P1/A4：冻结态 bash 里的 python/pip 调用拦截（目标机无系统 Python）
# ---------------------------------------------------------------------------

class TestBashPythonGuardHelpers:
    def test_segments_split_compound(self):
        from research_assistant.tools.bash import _segments

        assert _segments("cd x && python y.py") == ["cd x", "python y.py"]
        assert _segments("a | b & c; d || e") == ["a", "b", "c", "d", "e"]
        assert _segments("single") == ["single"]

    def test_is_python_invocation_matrix(self):
        from research_assistant.tools.bash import _is_python_invocation

        hits = [
            "python x.py", "python -V", "python3 script.py",
            "Python.exe -V", 'py -3 x.py', "pip install numpy",
            "PIP3 list", "python3.11 s.py",
            "FOO=1 BAR=2 python x.py",  # 前导环境变量赋值后命中
            r"C:\Windows\py.exe -3",    # 带路径的可执行名
        ]
        for seg in hits:
            assert _is_python_invocation(seg), seg

        misses = [
            "git status", "dir /b", "grep python f.txt", "echo python",
            "ipython --version", "", "   ",
        ]
        for seg in misses:
            assert not _is_python_invocation(seg), seg


class TestBashPythonGuardIntegration:
    async def test_frozen_blocks_direct_python(self, tmp_path, monkeypatch):
        import sys

        from research_assistant.tools.bash import run_bash

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        result = await run_bash("python make_fig.py", cwd=str(tmp_path))
        assert "run_python" in result
        assert "run_script" in result
        assert "sys.executable" in result

    async def test_frozen_blocks_compound_tail(self, tmp_path, monkeypatch):
        import sys

        from research_assistant.tools.bash import run_bash

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        result = await run_bash(
            "cd data && python plot.py", cwd=str(tmp_path))
        assert "run_script" in result

    async def test_frozen_blocks_pip(self, tmp_path, monkeypatch):
        import sys

        from research_assistant.tools.bash import run_bash

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        result = await run_bash("pip install requests", cwd=str(tmp_path))
        assert "run_python" in result

    async def test_unfrozen_passthrough(self, tmp_path, monkeypatch):
        import sys

        from research_assistant.tools.bash import run_bash

        monkeypatch.setattr(sys, "frozen", False, raising=False)
        result = await run_bash("echo guard_off", cwd=str(tmp_path))
        assert "guard_off" in result


# ---------------------------------------------------------------------------
# R12 P2/B2：write_file 写入归巢（write_anchor）——确定性落地规则
# ---------------------------------------------------------------------------

class TestWriteAnchor:
    async def test_relative_goes_to_anchor(self, tmp_path):
        from research_assistant.tools.file_ops import write_file

        anchor = tmp_path / "outputs" / "s1"
        anchor.mkdir(parents=True)
        await write_file(
            "fig/plot.py", "x=1", sandbox=str(tmp_path), write_anchor=str(anchor))
        assert (anchor / "fig" / "plot.py").read_text(encoding="utf-8") == "x=1"
        # 绝不落回工作区根（旧行为的散落根源）
        assert not (tmp_path / "fig" / "plot.py").exists()

    async def test_absolute_inside_sandbox_verbatim(self, tmp_path):
        from research_assistant.tools.file_ops import write_file

        anchor = tmp_path / "outputs" / "s1"
        anchor.mkdir(parents=True)
        target = tmp_path / "shared" / "f.md"
        await write_file(
            str(target), "hi", sandbox=str(tmp_path), write_anchor=str(anchor))
        assert target.read_text(encoding="utf-8") == "hi"
        assert not (anchor / "shared").exists()

    async def test_absolute_outside_sandbox_errors(self, tmp_path):
        from research_assistant.tools.file_ops import write_file

        anchor = tmp_path / "out"
        anchor.mkdir()
        outside = tmp_path.parent / "ra_anchor_escape_test.txt"
        result = await write_file(
            str(outside), "x", sandbox=str(tmp_path), write_anchor=str(anchor))
        assert "Error" in result
        assert not outside.exists()

    async def test_no_anchor_keeps_legacy_root_resolve(self, tmp_path):
        from research_assistant.tools.file_ops import write_file

        result = await write_file("rel.txt", "x", sandbox=str(tmp_path))
        assert (tmp_path / "rel.txt").read_text(encoding="utf-8") == "x"
        assert "Successfully" in result

    async def test_success_message_echoes_final_absolute_path(self, tmp_path):
        from research_assistant.tools.file_ops import write_file

        anchor = tmp_path / "outputs" / "s1"
        anchor.mkdir(parents=True)
        result = await write_file(
            "a.txt", "x", sandbox=str(tmp_path), write_anchor=str(anchor))
        assert str(anchor / "a.txt") in result  # 读写闭环 + files 启发式依赖


class TestRegistryAnchorPlumbing:
    async def test_write_file_receives_anchor_via_registry(self, tmp_path):
        anchor = tmp_path / "out"
        anchor.mkdir()
        reg = ToolRegistry(work_dir=str(tmp_path), write_anchor=str(anchor))
        await reg.execute("write_file", {"file_path": "x.txt", "content": "1"})
        assert (anchor / "x.txt").read_text(encoding="utf-8") == "1"

    async def test_exec_cwd_routes_bash_and_python(self, tmp_path):
        class Recorder:
            def __init__(self):
                self.bash_cwd = self.py_cwd = self.ws_root = None

            async def run_bash(self, command, timeout, cwd):
                self.bash_cwd = cwd
                return "ok"

            async def run_python(self, code, timeout, cwd, workspace_root=None):
                self.py_cwd = cwd
                self.ws_root = workspace_root
                return "ok"

        rec = Recorder()
        anchor = tmp_path / "out"
        anchor.mkdir()
        reg = ToolRegistry(
            work_dir=str(tmp_path), exec_cwd=str(anchor),
            exec_provider=rec,
        )
        await reg.execute("bash", {"command": "echo hi"})
        await reg.execute("run_python", {"code": "1"})
        assert rec.bash_cwd == str(anchor)   # 会话 bash/run_python 落产物目录
        assert rec.py_cwd == str(anchor)
        assert rec.ws_root == str(tmp_path)  # WS 恒为工作区根

    async def test_task_style_keeps_cwd_but_anchors_writes(self, tmp_path):
        """任务模式：exec_cwd 不传 → CWD 保持根；只加 write_anchor。"""
        anchor = tmp_path / "paper"
        anchor.mkdir()

        class Recorder:
            async def run_bash(self, command, timeout, cwd):
                TaskRegistryAnchorRecorder.last_cwd = cwd
                return "ok"

            async def run_python(self, code, timeout, cwd, workspace_root=None):
                return "ok"

        rec = Recorder()
        reg = ToolRegistry(
            work_dir=str(tmp_path), write_anchor=str(anchor), exec_provider=rec)
        await reg.execute("bash", {"command": "echo hi"})
        assert TaskRegistryAnchorRecorder.last_cwd == str(tmp_path)
        await reg.execute("write_file", {"file_path": "n.md", "content": "y"})
        assert (anchor / "n.md").exists()


class TaskRegistryAnchorRecorder:
    last_cwd: str | None = None
