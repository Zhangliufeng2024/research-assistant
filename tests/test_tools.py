"""Tests for research_assistant.tools — built-in tool implementations."""

import os
from pathlib import Path

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

    @pytest.mark.asyncio
    async def test_glob_rejects_path_outside_sandbox(self, tmp_path):
        outside = tmp_path.parent / "outside-glob"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")
        result = await glob_files("*", str(outside), sandbox=str(tmp_path))
        assert "escapes sandbox" in result
        assert "secret.txt" not in result


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

    @pytest.mark.asyncio
    async def test_grep_rejects_path_outside_sandbox(self, tmp_path):
        outside = tmp_path.parent / "outside-grep"
        outside.mkdir()
        (outside / "secret.txt").write_text("TOP SECRET")
        result = await grep_search("SECRET", str(outside), sandbox=str(tmp_path))
        assert "escapes sandbox" in result
        assert "TOP SECRET" not in result


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
    async def test_registry_search_tools_are_sandboxed(self, tmp_path):
        outside = tmp_path.parent / "outside-registry"
        outside.mkdir()
        (outside / "secret.txt").write_text("TOP SECRET")
        registry = ToolRegistry(work_dir=str(tmp_path))
        glob_result = await registry.execute(
            "glob_files", {"pattern": "*", "path": str(outside)},
        )
        grep_result = await registry.execute(
            "grep_search", {"pattern": "SECRET", "path": str(outside)},
        )
        assert "escapes sandbox" in glob_result
        assert "escapes sandbox" in grep_result

    @pytest.mark.asyncio
    async def test_registry_execute_run_python(self, tmp_path):
        registry = ToolRegistry(work_dir=str(tmp_path))
        result = await registry.execute("run_python", {"code": "print(1+2)"})
        assert "3" in result

    @pytest.mark.asyncio
    async def test_registry_versions_indirect_python_output(self, tmp_path):
        registry = ToolRegistry(work_dir=str(tmp_path))
        result = await registry.execute(
            "run_python",
            {"code": "from pathlib import Path\nPath('analysis.csv').write_text('x,y\\n1,2\\n')"},
        )
        assert "已记录 1 个脚本产物变更" in result
        changes = registry.version_store.list()
        assert changes[0]["path"] == "analysis.csv"
        assert changes[0]["tool"] == "run_python"

    @pytest.mark.asyncio
    async def test_registry_versions_indirect_script_deletion(self, tmp_path):
        doomed = tmp_path / "temporary.txt"
        doomed.write_text("remove me")

        class DeleteProvider:
            async def run_bash(self, command, timeout, cwd):
                (Path(cwd) / "temporary.txt").unlink()
                return "deleted"

            async def run_python(self, code, timeout, cwd, workspace_root=None):
                return "unused"

        registry = ToolRegistry(work_dir=str(tmp_path), exec_provider=DeleteProvider())
        result = await registry.execute("bash", {"command": "delete temporary.txt"})
        assert "已记录 1 个脚本产物变更" in result
        change = registry.version_store.list()[0]
        assert change["path"] == "temporary.txt"
        assert change["before_exists"] is True
        assert change["after_exists"] is False

    @pytest.mark.asyncio
    async def test_registry_rejects_execution_cwd_outside_workspace(self, tmp_path):
        registry = ToolRegistry(work_dir=str(tmp_path))
        result = await registry.execute("run_python", {"code": "print('x')", "cwd": str(tmp_path.parent)})
        assert "escapes workspace" in result

    def test_run_python_in_definitions(self):
        names = [td["name"] for td in TOOL_DEFINITIONS]
        assert "run_python" in names


class TestCitationSandbox:
    @pytest.mark.asyncio
    async def test_output_path_is_rejected_before_network_work(
            self, tmp_path, monkeypatch):
        from research_assistant.tools import citation_verify

        bib = tmp_path / "refs.bib"
        bib.write_text("@article{x, title={X}}")
        outside = tmp_path.parent / "citation-report.md"
        called = False

        async def fake_verify(path):
            nonlocal called
            called = True
            raise AssertionError("sandbox validation must happen first")

        monkeypatch.setattr(citation_verify, "verify_bibtex_file", fake_verify)
        result = await citation_verify.verify_citations(
            str(bib), output_file=str(outside), sandbox=str(tmp_path),
        )
        assert "output_file path escapes sandbox" in result
        assert called is False
        assert not outside.exists()


class TestCitationSimilarityNormalization:
    """Guard: title similarity ignores BibTeX brace protection characters.

    parse_bibtex now preserves inner braces verbatim (e.g.
    ``Deep {Learning} Approaches``).  These tests pin the existing property of
    ``_normalize``/``_jaccard`` that such braces never distort similarity, so
    protected-casing titles compare cleanly against API-returned titles.
    """

    def test_normalize_strips_braces(self):
        from research_assistant.tools.citation_verify import _normalize

        assert _normalize("Deep {Learning} Approaches") == "deep learning approaches"
        assert "{" not in _normalize("{SiO_{2}} Coatings")
        assert "}" not in _normalize("{SiO_{2}} Coatings")

    def test_jaccard_ignores_brace_protection(self):
        from research_assistant.tools.citation_verify import _jaccard

        # Same tokenization -- brace protection alone must not move similarity.
        braced = "Deep {Learning} Approaches for {Shm} Systems"
        plain = "Deep Learning Approaches for SHM SYSTEMS"
        assert _jaccard(braced, plain) == 1.0


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


# ---------------------------------------------------------------------------
# 安全修复 D：冻结态 python 拦截加固（换行藏毒 / 引号路径 / call-start-cmd 前缀）
# ---------------------------------------------------------------------------

class TestBashPythonGuardHardening:
    def test_segments_split_newlines(self):
        from research_assistant.tools.bash import _segments

        # cmd.exe 把裸 LF 当命令分隔符——不切行就会漏检换行藏毒
        assert _segments("dir\npython x.py") == ["dir", "python x.py"]
        assert _segments("dir\r\npython x.py") == ["dir", "python x.py"]
        assert _segments("a && b\nc") == ["a", "b", "c"]

    def test_is_python_invocation_hardened_matrix(self):
        from research_assistant.tools.bash import _is_python_invocation

        hits = [
            '"python.exe" -V',
            r'"C:\Program Files\Python312\python.exe" x.py',  # 引号包裹带空格路径
            r"call python -V",
            r'start "" python -V',
            r'start "My App" python x.py',
            r"cmd /c python -V",
            r"cmd /d /c pip install numpy",
            r'call "C:\Program Files\Python312\python.exe" s.py',
            r"call cmd /c python x.py",  # 前缀链嵌套
        ]
        for seg in hits:
            assert _is_python_invocation(seg), seg

        misses = [
            "where python",           # 查询不是调用
            "dir",
            r'start "" notepad',      # start 标题后的普通程序
            r"call helper.bat",
            "cmd /c dir /b",
            "echo python",
        ]
        for seg in misses:
            assert not _is_python_invocation(seg), seg


class TestBashPythonGuardHardeningIntegration:
    async def test_frozen_blocks_newline_smuggled_python(self, tmp_path, monkeypatch):
        import sys

        from research_assistant.tools.bash import run_bash

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        result = await run_bash("dir\npython x.py", cwd=str(tmp_path))
        assert "打包环境" in result

    async def test_frozen_blocks_quoted_exe_path(self, tmp_path, monkeypatch):
        import sys

        from research_assistant.tools.bash import run_bash

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        result = await run_bash(
            r'"C:\Program Files\Python312\python.exe" x.py', cwd=str(tmp_path))
        assert "打包环境" in result

    async def test_frozen_blocks_call_and_cmd_prefixes(self, tmp_path, monkeypatch):
        import sys

        from research_assistant.tools.bash import run_bash

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        for command in ("call python -V", 'start "" python -V', "cmd /c python -V"):
            result = await run_bash(command, cwd=str(tmp_path))
            assert "打包环境" in result, command

    async def test_frozen_allows_where_python_and_dir(self, tmp_path, monkeypatch):
        import sys

        from research_assistant.tools.bash import run_bash

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        where_result = await run_bash("where python", cwd=str(tmp_path))
        dir_result = await run_bash("dir", cwd=str(tmp_path))
        assert "打包环境" not in where_result
        assert "打包环境" not in dir_result


# ---------------------------------------------------------------------------
# 安全修复 C：围栏参数无条件覆盖——模型伪造 sandbox/write_anchor 键无效
# ---------------------------------------------------------------------------

class TestRegistryFenceOverride:
    @pytest.mark.asyncio
    async def test_forged_sandbox_cannot_widen_fence(self, tmp_path):
        outside = tmp_path.parent / "outside-forge-sandbox"
        outside.mkdir(exist_ok=True)
        (outside / "secret.txt").write_text("TOP SECRET")
        registry = ToolRegistry(work_dir=str(tmp_path))
        result = await registry.execute(
            "read_file",
            {
                "file_path": str(outside / "secret.txt"),
                "sandbox": "C:\\Users",  # 模型自带的伪造围栏
            },
        )
        assert "Error" in result
        assert "TOP SECRET" not in result

    @pytest.mark.asyncio
    async def test_forged_write_anchor_is_dropped(self, tmp_path):
        anchor = tmp_path / "out"
        anchor.mkdir()
        forged = tmp_path.parent / "forged-anchor"
        forged.mkdir(exist_ok=True)
        registry = ToolRegistry(work_dir=str(tmp_path), write_anchor=str(anchor))
        result = await registry.execute(
            "write_file",
            {
                "file_path": "x.txt",
                "content": "1",
                "write_anchor": str(forged),  # 模型伪造的归巢点
            },
        )
        assert "Successfully" in result
        assert (anchor / "x.txt").read_text(encoding="utf-8") == "1"
        assert not (forged / "x.txt").exists()


# ---------------------------------------------------------------------------
# 修复 G：write/edit/read 相对路径同一 anchor 口径（双轨一致性）
# ---------------------------------------------------------------------------

class TestDualTrackConsistency:
    @pytest.mark.asyncio
    async def test_anchor_roundtrip_write_edit_read(self, tmp_path):
        """纯会话场景（无同名根文件）：write→edit→read 全部命中 anchor 同一文件。"""
        anchor = tmp_path / "outputs" / "s1"
        anchor.mkdir(parents=True)

        reg = ToolRegistry(work_dir=str(tmp_path), write_anchor=str(anchor))
        w = await reg.execute(
            "write_file", {"file_path": "draft.md", "content": "session draft v1"})
        e = await reg.execute(
            "edit_file", {"file_path": "draft.md", "old_string": "v1", "new_string": "v2"})
        r = await reg.execute("read_file", {"file_path": "draft.md"})
        assert "Successfully" in w
        assert "Successfully" in e
        assert "session draft v2" in r
        assert (anchor / "draft.md").read_text(encoding="utf-8") == "session draft v2"

    @pytest.mark.asyncio
    async def test_root_duplicate_not_clobbered_by_session_roundtrip(self, tmp_path):
        """根下存在同名共享文件：写入/编辑命中 anchor 副本，根文件不被误改。"""
        anchor = tmp_path / "outputs" / "s1"
        anchor.mkdir(parents=True)
        root_draft = tmp_path / "draft.md"
        root_draft.write_text("root version\n", encoding="utf-8")

        reg = ToolRegistry(work_dir=str(tmp_path), write_anchor=str(anchor))
        await reg.execute(
            "write_file", {"file_path": "draft.md", "content": "session draft v1"})
        e = await reg.execute(
            "edit_file", {"file_path": "draft.md", "old_string": "v1", "new_string": "v2"})
        assert "Successfully" in e
        # 会话副本被编辑；根下共享文件原样未动
        assert (anchor / "draft.md").read_text(encoding="utf-8") == "session draft v2"
        assert root_draft.read_text(encoding="utf-8") == "root version\n"
        # read 按规格是「根优先、根缺失才回退 anchor」——此处读到根副本
        r = await reg.execute("read_file", {"file_path": "draft.md"})
        assert "root version" in r

    @pytest.mark.asyncio
    async def test_read_relative_root_hit_unchanged(self, tmp_path):
        # pipeline 兼容：相对路径在根下存在时旧行为完全不变
        (tmp_path / "shared.txt").write_text("root copy", encoding="utf-8")
        anchor = tmp_path / "out"
        anchor.mkdir()
        reg = ToolRegistry(work_dir=str(tmp_path), write_anchor=str(anchor))
        result = await reg.execute("read_file", {"file_path": "shared.txt"})
        assert "root copy" in result

    @pytest.mark.asyncio
    async def test_edit_relative_falls_back_to_root_when_not_in_anchor(self, tmp_path):
        # anchor 已设但该相对路径只在根下存在 → 编辑根下共享文件（旧语义保留）
        (tmp_path / "shared.md").write_text("hello world", encoding="utf-8")
        anchor = tmp_path / "out"
        anchor.mkdir()
        reg = ToolRegistry(work_dir=str(tmp_path), write_anchor=str(anchor))
        result = await reg.execute(
            "edit_file", {"file_path": "shared.md", "old_string": "world", "new_string": "there"})
        assert "Successfully" in result
        assert (tmp_path / "shared.md").read_text(encoding="utf-8") == "hello there"

    @pytest.mark.asyncio
    async def test_handler_level_read_falls_back_to_anchor(self, tmp_path):
        anchor = tmp_path / "out"
        anchor.mkdir()
        (anchor / "only_in_anchor.txt").write_text("anchored!", encoding="utf-8")
        result = await read_file(
            "only_in_anchor.txt", sandbox=str(tmp_path), write_anchor=str(anchor))
        assert "anchored!" in result

    @pytest.mark.asyncio
    async def test_edit_gbk_legacy_file_does_not_crash(self, tmp_path):
        # GBK 存量文件可编不可崩：ASCII 锚点替换成功即可
        f = tmp_path / "legacy.txt"
        f.write_bytes("value = 1\r\n# 中文注释\r\n".encode("gbk"))
        result = await edit_file(str(f), "value = 1", "value = 2")
        assert "Successfully" in result
        assert b"value = 2" in f.read_bytes()


# ---------------------------------------------------------------------------
# 修复 H：write_file 拒绝 Windows 保留设备名与 NTFS 备用数据流（ADS）
# ---------------------------------------------------------------------------

class TestWriteFileWindowsHazards:
    @pytest.mark.asyncio
    async def test_reserved_device_name_rejected(self, tmp_path):
        result = await write_file(
            str(tmp_path / "con.txt"), "x", sandbox=str(tmp_path))
        assert "Error" in result
        assert not (tmp_path / "con.txt").exists()

    @pytest.mark.asyncio
    async def test_reserved_device_name_bare_rejected(self, tmp_path):
        result = await write_file(
            str(tmp_path / "NUL"), "x", sandbox=str(tmp_path))
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ads_colon_rejected(self, tmp_path):
        result = await write_file(
            str(tmp_path / "report:hidden.txt"), "x", sandbox=str(tmp_path))
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_mid_path_colon_rejected(self, tmp_path):
        result = await write_file(
            str(tmp_path / "sub:stream" / "a.txt"), "x", sandbox=str(tmp_path))
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_normal_name_starting_with_con_still_allowed(self, tmp_path):
        result = await write_file(
            str(tmp_path / "concrete.md"), "x", sandbox=str(tmp_path))
        assert "Successfully" in result
        assert (tmp_path / "concrete.md").read_text(encoding="utf-8") == "x"
