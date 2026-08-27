"""Tests for the frozen-mode Python executor (tools/frozen_exec).

冻结版没有独立解释器可调（sys.executable 是应用自身），run_python 在
``sys.frozen`` 时改走本模块——spawn 独立子进程执行、超时强杀。这里直接
测执行器本身，另用 monkeypatch 把 ``sys.frozen`` 置真验证 python_exec
的分流。
"""

import sys

import pytest

from research_assistant.tools.frozen_exec import run_python_inprocess

matplotlib = pytest.importorskip("matplotlib")


@pytest.mark.asyncio()
class TestRunPythonInprocess:
    async def test_stdout_captured(self, tmp_path):
        result = await run_python_inprocess("print(6 * 7)", cwd=str(tmp_path))
        assert result.strip() == "42"

    async def test_exception_reported(self, tmp_path):
        result = await run_python_inprocess("raise ValueError('boom')", cwd=str(tmp_path))
        assert "ValueError" in result
        assert "boom" in result

    async def test_systemexit_not_fatal(self, tmp_path):
        result = await run_python_inprocess("import sys; sys.exit(3)", cwd=str(tmp_path))
        assert "exit: 3" in result

    async def test_runaway_killed_on_timeout(self, tmp_path):
        # 死循环：子进程被强杀，父进程（应用）不受影响、测试秒级返回
        result = await run_python_inprocess("while True: pass", timeout=2, cwd=str(tmp_path))
        assert "timed out" in result

    async def test_child_cwd_isolated_from_parent(self, tmp_path):
        sentinel = tmp_path / "marker.txt"
        code = "import os\nopen('marker.txt', 'w').write('ok')\nprint(os.getcwd())\n"
        result = await run_python_inprocess(code, cwd=str(tmp_path))
        assert sentinel.read_text(encoding="utf-8") == "ok"
        assert str(tmp_path) in result
        # chdir 只发生在子进程：父进程 CWD 不动

    async def test_matplotlib_agg_savefig(self, tmp_path):
        # cowork 交付物的核心场景：打包环境内真正画图落盘
        code = (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "fig, ax = plt.subplots()\n"
            "ax.plot([0, 1], [0, 1])\n"
            "fig.savefig('figure.png', dpi=72)\n"
            "print('saved')\n"
        )
        result = await run_python_inprocess(code, cwd=str(tmp_path))
        assert "saved" in result
        assert (tmp_path / "figure.png").stat().st_size > 0


class TestFrozenDispatch:
    def test_run_python_routes_to_inprocess_when_frozen(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        # python_exec 在函数体内延迟导入 frozen_exec——monkeypatch 源模块即可
        import asyncio

        import research_assistant.tools.frozen_exec as fe
        from research_assistant.tools import python_exec

        called = {}

        async def fake_inprocess(code, timeout=120, cwd=".", workspace_root=None):
            called["code"] = code
            return "in-process!"

        monkeypatch.setattr(fe, "run_python_inprocess", fake_inprocess)
        got = asyncio.run(python_exec.run_python("print('x')", cwd=str(tmp_path)))
        assert got == "in-process!"
        assert called["code"] == "print('x')"


# ---------------------------------------------------------------------------
# R12 P1/A3：子进程内注入 run_script 助手与 WS 工作区根常量
# ---------------------------------------------------------------------------

class TestRunScriptHelper:
    async def test_ws_global_is_workspace_root(self, tmp_path):
        ws = tmp_path / "wsroot"
        ws.mkdir()
        result = await run_python_inprocess("print(WS)", cwd=str(tmp_path), workspace_root=str(ws))
        assert str(ws) in result

    async def test_ws_default_empty_when_not_passed(self, tmp_path):
        result = await run_python_inprocess("print(repr(WS))", cwd=str(tmp_path))
        assert "''" in result

    async def test_run_script_argv_and_main_guard(self, tmp_path):
        script = tmp_path / "tool.py"
        script.write_text(
            "import sys\n"
            "print(sys.argv[1:])\n"
            "print('main' if __name__ == '__main__' else 'imported')\n",
            encoding="utf-8",
        )
        result = await run_python_inprocess(
            f"run_script(r'{script}', ['a', 'b'])", cwd=str(tmp_path))
        assert "['a', 'b']" in result
        assert "main" in result

    async def test_run_script_file_dunder(self, tmp_path):
        script = tmp_path / "me.py"
        script.write_text("print(__file__)\n", encoding="utf-8")
        result = await run_python_inprocess(f"run_script(r'{script}')", cwd=str(tmp_path))
        assert str(script) in result

    async def test_sibling_module_import(self, tmp_path):
        (tmp_path / "helper_mod.py").write_text("VALUE = 41\n", encoding="utf-8")
        main = tmp_path / "use_helper.py"
        main.write_text(
            "from helper_mod import VALUE\nprint(VALUE + 1)\n", encoding="utf-8")
        result = await run_python_inprocess(f"run_script(r'{main}')", cwd=str(tmp_path))
        assert "42" in result

    async def test_missing_script_gives_guidance(self, tmp_path):
        result = await run_python_inprocess(
            "print(run_script('no_such_script.py'))", cwd=str(tmp_path))
        assert "Error" in result
        assert "no_such_script.py" in result

    async def test_run_script_restores_argv(self, tmp_path):
        inner = tmp_path / "inner.py"
        inner.write_text("pass\n", encoding="utf-8")
        outer = tmp_path / "outer.py"
        outer.write_text(
            "import sys\n"
            "before = list(sys.argv)\n"
            "run_script(r'" + str(inner).replace("\\", "\\\\") + "', ['x'])\n"
            "print('restored' if sys.argv == before else 'LEAKED')\n",
            encoding="utf-8",
        )
        # 外层经 run_python 的代码本身带 argv 注入路径，验证脚本内部嵌套调用后恢复
        result = await run_python_inprocess(
            f"run_script(r'{outer}', ['keep', 'me'])", cwd=str(tmp_path))
        assert "restored" in result

    async def test_systemexit_inside_script_reported_not_fatal(self, tmp_path):
        script = tmp_path / "quitter.py"
        script.write_text(
            "import sys\nraise SystemExit(3)\n", encoding="utf-8")
        result = await run_python_inprocess(
            f"run_script(r'{script}')\nprint('after')", cwd=str(tmp_path))
        assert "(exit: 3)" in result
        assert "after" in result


class TestPythonExecForwardsWorkspaceRoot:
    def test_frozen_dispatch_forwards_workspace_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        import research_assistant.tools.frozen_exec as fe
        from research_assistant.tools import python_exec

        captured: dict = {}

        async def fake_inprocess(code, timeout=120, cwd=".", workspace_root=None):
            captured["workspace_root"] = workspace_root
            return "in-process!"

        monkeypatch.setattr(fe, "run_python_inprocess", fake_inprocess)
        import asyncio

        got = asyncio.run(python_exec.run_python(
            "print('x')", cwd=str(tmp_path), workspace_root="/ws"))
        assert got == "in-process!"
        assert captured["workspace_root"] == "/ws"


# ---------------------------------------------------------------------------
# 修复 E：子进程异常退出码必须显式回报；临时输出文件清理失败要留痕
# ---------------------------------------------------------------------------

class TestChildExitCodeReporting:
    async def test_nonzero_exit_code_appended(self, tmp_path):
        # os._exit 绕过 _child_main 的异常捕获：真实传递非 0 返回码的场景
        code = (
            "print('partial')\n"
            "import sys; sys.stdout.flush()\n"
            "import os; os._exit(7)\n"
        )
        result = await run_python_inprocess(code, cwd=str(tmp_path))
        assert "partial" in result
        assert "exitcode=7" in result

    async def test_clean_exit_has_no_marker(self, tmp_path):
        result = await run_python_inprocess("print('ok')", cwd=str(tmp_path))
        assert "exitcode" not in result


class TestTempOutputCleanupLogging:
    async def test_unlink_failure_logs_warning(self, tmp_path, monkeypatch, caplog):
        import logging
        import os as _os

        real_unlink = _os.unlink

        def flaky_unlink(path, *args, **kwargs):
            if "_ra_exec_out_" in str(path):
                raise PermissionError(32, "simulated lock")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(_os, "unlink", flaky_unlink)
        with caplog.at_level(logging.WARNING, logger="research_assistant.tools.frozen_exec"):
            result = await run_python_inprocess("print('hi')", cwd=str(tmp_path))
        assert "hi" in result  # 功能不受清理失败影响
        assert "_ra_exec_out_" in caplog.text  # 不再静默 pass
