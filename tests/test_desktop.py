"""Tests for research_assistant.desktop — 入口防线（R12 P1/A5）。

只测可导入的纯逻辑（工作区参数分类），不启动窗口/服务。
模块顶部无 tkinter/webview 依赖，import 安全。
"""

from research_assistant.desktop import workspace_arg_error


class TestWorkspaceArgError:
    def test_existing_directory_ok(self, tmp_path):
        assert workspace_arg_error(str(tmp_path)) is None

    def test_nonexistent_path_generic_message(self, tmp_path):
        missing = tmp_path / "no_such_dir"
        msg = workspace_arg_error(str(missing))
        assert msg is not None
        assert "目录不存在" in msg
        assert str(missing) in msg

    def test_file_argument_gets_targeted_guidance(self, tmp_path):
        """目标机事故的直接症状：脚本把 .py 文件当工作区参数传进来——
        必须解释 sys.executable 成因并指向 run_python，而非泛泛的目录不存在。"""
        f = tmp_path / "make_fig7.py"
        f.write_text("print('x')", encoding="utf-8")
        msg = workspace_arg_error(str(f))
        assert msg is not None
        assert "文件" in msg
        assert "sys.executable" in msg
        assert "run_python" in msg


class TestDesktopShellOpenGate:
    def test_main_sets_allow_shell_open_default(self):
        """桌面壳受信：main() 应把 RA_ALLOW_SHELL_OPEN 默认置 1
        （dock 的「打开所在文件夹」依赖它；显式设置的用户值不被覆盖）。"""
        import inspect
        import re

        from research_assistant import desktop

        source = inspect.getsource(desktop.main)
        assert re.search(
            r'setdefault\(\s*"RA_ALLOW_SHELL_OPEN",\s*"1"', source
        )
