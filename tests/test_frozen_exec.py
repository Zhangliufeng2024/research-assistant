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

        async def fake_inprocess(code, timeout=120, cwd="."):
            called["code"] = code
            return "in-process!"

        monkeypatch.setattr(fe, "run_python_inprocess", fake_inprocess)
        got = asyncio.run(python_exec.run_python("print('x')", cwd=str(tmp_path)))
        assert got == "in-process!"
        assert called["code"] == "print('x')"
