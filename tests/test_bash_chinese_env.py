"""中文 Windows 环境下 bash/python 工具的本地化与窗口静默测试。

用户实测 bug 复现（Bug A）：中文 Windows 上 cmd.exe 内建命令经管道输出
GBK(cp936) 字节，bash.py / python_exec.py 一律按 utf-8+replace 解码，
「dir」「echo 中文」全部变成乱码——表现为「遇到中文路径无法识别」。
复现方式：tempfile 建中文名目录，cd 后跑 ``dir`` 与 ``echo 你好好``，
断言输出包含完整中文路径/文字。

附带 Bug B 的回归：Windows 下所有子进程创建点必须传 CREATE_NO_WINDOW，
桌面应用（无控制台）里执行命令不得闪现终端窗体。
"""

import subprocess
import sys

import pytest

from research_assistant.tools.bash import _run_process, decode_process_output, run_bash


class TestDecodeProcessOutput:
    """解码兜底链的单测（不依赖本机代码页，任何环境都确定）。"""

    def test_utf8_roundtrip(self):
        assert decode_process_output("你好世界".encode()) == "你好世界"

    def test_gbk_fallback(self):
        # cmd.exe 内建命令在中文 Windows 管道上的真实形态：GBK 字节
        raw = "中文 目录\\数据.txt".encode("gbk")
        assert decode_process_output(raw) == "中文 目录\\数据.txt"

    def test_ascii_passthrough(self):
        assert decode_process_output(b"plain ascii") == "plain ascii"

    def test_never_raises_on_binary_garbage(self):
        # 非法 utf-8 且非法 gbk 的杂凑字节也不允许抛异常
        result = decode_process_output(b"\xff\xfe\x81\x40")
        assert isinstance(result, str)


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe 行为仅 Windows")
class TestBashChineseOutput:
    """端到端复现：真 cmd.exe 的 GBK 输出必须完整还原中文。"""

    @pytest.mark.asyncio
    async def test_dir_shows_chinese_path(self, tmp_path):
        d = tmp_path / "中文 目录"
        d.mkdir()
        (d / "数据.txt").write_text("x", encoding="utf-8")
        result = await run_bash("dir", cwd=str(d))
        assert "Error" not in result or "Exit code" in result  # 命令本身应成功
        assert "中文 目录" in result, f"cmd dir 输出丢失中文路径: {result[:200]!r}"

    @pytest.mark.asyncio
    async def test_echo_chinese_text(self, tmp_path):
        # 同时验证 argv 传参层面：CreateProcessW 宽字符传参 + 输出解码全链路
        result = await run_bash("echo 你好好", cwd=str(tmp_path))
        assert "你好好" in result, f"echo 中文回显乱码: {result[:200]!r}"


@pytest.mark.skipif(sys.platform != "win32", reason="CREATE_NO_WINDOW 仅 Windows")
class TestSilentSubprocessOnWindows:
    """Bug B 回归：win32 分支的 Popen 必须带 CREATE_NO_WINDOW。"""

    @pytest.mark.asyncio
    async def test_popen_gets_create_no_window(self, monkeypatch):
        captured: dict = {}

        class FakeProc:
            returncode = 0

            def communicate(self, timeout=None):
                return b"", b""

        def fake_popen(args, **kwargs):
            captured.update(kwargs)
            return FakeProc()

        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        code, out, err = await _run_process(
            ["cmd", "/c", "echo x"], cwd=".", timeout=5,
        )
        assert (code, out, err) == (0, b"", b"")
        assert captured.get("creationflags") == getattr(
            subprocess, "CREATE_NO_WINDOW", 0,
        ), "win32 子进程缺少 CREATE_NO_WINDOW（会闪终端窗）"

    @pytest.mark.asyncio
    async def test_run_python_child_env_injects_pythonutf8(self, tmp_path, monkeypatch):
        # 开发态分支：给 python 子进程注入 PYTHONUTF8=1，从源头减少乱码（Bug A）
        from research_assistant.tools import python_exec

        captured: dict = {}

        async def fake_run(args, *, cwd, timeout, env=None):
            captured["env"] = env
            return 0, b"ok", b""

        monkeypatch.setattr(python_exec, "_run_process", fake_run)
        result = await python_exec.run_python("print(1)", cwd=str(tmp_path))
        assert result.strip() == "ok"
        env = captured.get("env")
        assert env is not None, "开发态 python 子进程未注入环境变量"
        assert env.get("PYTHONUTF8") == "1"
        # 必须是完整环境副本（不能丢 PATH 等）
        assert "PATH" in env
