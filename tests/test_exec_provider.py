"""Tests for the execution provider seam (research_assistant.tools.exec_provider).

The seam lets the whole bash/run_python tool family move to a different
execution world (container, remote sandbox) without touching tool definitions.
These tests pin down: the local provider's behavior, the registry's default
provider, argument routing through a custom provider, and the timeout
regression that must survive the seam.
"""

import os

import pytest

from research_assistant.tools.exec_provider import ExecProvider, LocalExecProvider
from research_assistant.tools.registry import ToolRegistry


class TestLocalExecProvider:
    @pytest.mark.asyncio
    async def test_run_bash_returns_output(self, tmp_path):
        provider = LocalExecProvider()
        result = await provider.run_bash("echo seam_bash_ok", timeout=30, cwd=str(tmp_path))
        assert "seam_bash_ok" in result

    @pytest.mark.asyncio
    async def test_run_bash_cwd_is_respected(self, tmp_path):
        # Output redirection works in both cmd.exe and POSIX sh.
        provider = LocalExecProvider()
        await provider.run_bash("echo cwd_marker > _seam_out.txt", timeout=30, cwd=str(tmp_path))
        assert (tmp_path / "_seam_out.txt").read_text().strip().endswith("cwd_marker")

    @pytest.mark.asyncio
    async def test_run_python_returns_output(self, tmp_path):
        provider = LocalExecProvider()
        result = await provider.run_python("print('seam_python_ok')", timeout=30, cwd=str(tmp_path))
        assert "seam_python_ok" in result

    @pytest.mark.asyncio
    async def test_run_python_timeout(self, tmp_path):
        provider = LocalExecProvider()
        result = await provider.run_python(
            "import time; time.sleep(5)", timeout=1, cwd=str(tmp_path)
        )
        assert "timed out" in result

    def test_local_provider_satisfies_protocol(self):
        assert isinstance(LocalExecProvider(), ExecProvider)


class TestRegistryDefaultProvider:
    def test_default_exec_provider_is_local(self):
        registry = ToolRegistry()
        assert isinstance(registry.exec_provider, LocalExecProvider)
        assert isinstance(registry.exec_provider, ExecProvider)

    def test_explicit_provider_is_kept(self):
        provider = LocalExecProvider()
        registry = ToolRegistry(exec_provider=provider)
        assert registry.exec_provider is provider


class FakeExecProvider:
    """Records calls and returns a sentinel string (structural ExecProvider)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def run_bash(self, command: str, timeout: int, cwd: str) -> str:
        self.calls.append(("bash", {"command": command, "timeout": timeout, "cwd": cwd}))
        return "SENTINEL_BASH"

    async def run_python(
        self, code: str, timeout: int, cwd: str,
        workspace_root: str | None = None,
    ) -> str:
        self.calls.append(("python", {
            "code": code, "timeout": timeout, "cwd": cwd,
            "workspace_root": workspace_root,
        }))
        return "SENTINEL_PYTHON"


class TestRegistryRoutesThroughProvider:
    @pytest.mark.asyncio
    async def test_bash_routed_to_provider(self, tmp_path):
        fake = FakeExecProvider()
        registry = ToolRegistry(work_dir=str(tmp_path), exec_provider=fake)
        result = await registry.execute("bash", {"command": "echo hi", "timeout": 5})
        assert result == "SENTINEL_BASH"
        assert fake.calls == [("bash", {"command": "echo hi", "timeout": 5, "cwd": str(tmp_path)})]

    @pytest.mark.asyncio
    async def test_run_python_routed_to_provider(self, tmp_path):
        fake = FakeExecProvider()
        registry = ToolRegistry(work_dir=str(tmp_path), exec_provider=fake)
        result = await registry.execute("run_python", {"code": "print(1)", "timeout": 7})
        assert result == "SENTINEL_PYTHON"
        # R12 P1：registry 把工作区根作为 workspace_root 传给 provider
        assert fake.calls == [
            ("python", {
                "code": "print(1)", "timeout": 7, "cwd": str(tmp_path),
                "workspace_root": str(tmp_path),
            })
        ]

    @pytest.mark.asyncio
    async def test_bash_defaults_injected(self, tmp_path):
        fake = FakeExecProvider()
        registry = ToolRegistry(work_dir=str(tmp_path), exec_provider=fake)
        await registry.execute("bash", {"command": "echo hi"})
        assert fake.calls[0][1]["timeout"] == 120
        assert fake.calls[0][1]["cwd"] == str(tmp_path)

    @pytest.mark.asyncio
    async def test_run_python_defaults_injected(self, tmp_path):
        fake = FakeExecProvider()
        registry = ToolRegistry(work_dir=str(tmp_path), exec_provider=fake)
        await registry.execute("run_python", {"code": "x = 1"})
        assert fake.calls[0][1]["timeout"] == 120
        assert fake.calls[0][1]["cwd"] == str(tmp_path)
        assert fake.calls[0][1]["workspace_root"] == str(tmp_path)

    @pytest.mark.asyncio
    async def test_bash_explicit_path_maps_to_cwd(self, tmp_path):
        # Preserved behavior: a caller-supplied "path" becomes the bash cwd.
        other = tmp_path / "other"
        other.mkdir()
        fake = FakeExecProvider()
        registry = ToolRegistry(work_dir=str(tmp_path), exec_provider=fake)
        await registry.execute("bash", {"command": "echo hi", "path": str(other)})
        assert fake.calls[0][1]["cwd"] == str(other)

    @pytest.mark.asyncio
    async def test_run_python_explicit_cwd_passes_through(self, tmp_path):
        other = tmp_path / "elsewhere"
        other.mkdir()
        fake = FakeExecProvider()
        registry = ToolRegistry(work_dir=str(tmp_path), exec_provider=fake)
        await registry.execute("run_python", {"code": "x = 1", "cwd": str(other)})
        assert fake.calls[0][1]["cwd"] == str(other)

    @pytest.mark.asyncio
    async def test_provider_exception_is_wrapped(self, tmp_path):
        class ExplodingProvider:
            async def run_bash(self, command: str, timeout: int, cwd: str) -> str:
                raise RuntimeError("world unavailable")

            async def run_python(
                self, code: str, timeout: int, cwd: str,
                workspace_root: str | None = None,
            ) -> str:
                raise RuntimeError("world unavailable")

        registry = ToolRegistry(work_dir=str(tmp_path), exec_provider=ExplodingProvider())
        result = await registry.execute("bash", {"command": "echo hi"})
        assert "Error executing bash" in result
        assert "world unavailable" in result

    def test_fake_provider_satisfies_protocol(self):
        assert isinstance(FakeExecProvider(), ExecProvider)


class TestRegistryRegression:
    @pytest.mark.asyncio
    async def test_bash_timeout_via_registry(self, tmp_path):
        registry = ToolRegistry(work_dir=str(tmp_path))
        # 修复 F：registry 层超时钳位下限 5s——命令须长于 5 秒才能触发超时
        if os.name == "nt":
            command = "ping -n 30 127.0.0.1"
        else:
            command = "sleep 8"
        result = await registry.execute("bash", {"command": command, "timeout": 1})
        assert "Error: Command timed out" in result

    @pytest.mark.asyncio
    async def test_run_python_still_executes_via_default_provider(self, tmp_path):
        registry = ToolRegistry(work_dir=str(tmp_path))
        result = await registry.execute("run_python", {"code": "print(1 + 2)"})
        assert "3" in result

    @pytest.mark.asyncio
    async def test_non_provider_tools_unaffected(self, tmp_path):
        f = tmp_path / "note.txt"
        f.write_text("seam does not touch file tools")
        registry = ToolRegistry(work_dir=str(tmp_path))
        result = await registry.execute("read_file", {"file_path": str(f)})
        assert "seam does not touch file tools" in result

    @pytest.mark.asyncio
    async def test_unknown_tool_still_reported(self):
        registry = ToolRegistry()
        result = await registry.execute("nonexistent_tool", {})
        assert "Unknown tool" in result


# ---------------------------------------------------------------------------
# R12 P1/A3：workspace_root 沿 registry → provider → frozen 执行器贯通
# ---------------------------------------------------------------------------

class TestWorkspaceRootForwarding:
    @pytest.mark.asyncio
    async def test_registry_passes_workspace_root_to_provider(self, tmp_path):
        class RootRecorder(FakeExecProvider):
            async def run_python(
                self, code: str, timeout: int, cwd: str,
                workspace_root: str | None = None,
            ) -> str:
                self.seen_root = workspace_root
                return "OK"

        rec = RootRecorder()
        registry = ToolRegistry(work_dir=str(tmp_path), exec_provider=rec)
        await registry.execute("run_python", {"code": "x = 1"})
        assert rec.seen_root == str(tmp_path)

    def test_local_provider_satisfies_protocol_with_new_kwarg(self):
        # 协议加性扩展后，LocalExecProvider 仍满足 ExecProvider
        assert isinstance(LocalExecProvider(), ExecProvider)

    def test_run_python_protocol_signature_has_workspace_root(self):
        import inspect

        sig = inspect.signature(ExecProvider.run_python)
        assert "workspace_root" in sig.parameters
        assert sig.parameters["workspace_root"].default is None


# ---------------------------------------------------------------------------
# 修复 F：registry 层执行超时钳位到 [5, 600] 秒
# ---------------------------------------------------------------------------

class TestTimeoutClamp:
    @pytest.mark.asyncio
    async def test_bash_timeout_clamped_to_max(self, tmp_path):
        fake = FakeExecProvider()
        registry = ToolRegistry(work_dir=str(tmp_path), exec_provider=fake)
        await registry.execute("bash", {"command": "echo hi", "timeout": 99999})
        assert fake.calls[0][1]["timeout"] == 600

    @pytest.mark.asyncio
    async def test_bash_timeout_clamped_to_min(self, tmp_path):
        fake = FakeExecProvider()
        registry = ToolRegistry(work_dir=str(tmp_path), exec_provider=fake)
        await registry.execute("bash", {"command": "echo hi", "timeout": 0})
        assert fake.calls[0][1]["timeout"] == 5

    @pytest.mark.asyncio
    async def test_run_python_timeout_clamped_both_ends(self, tmp_path):
        fake = FakeExecProvider()
        registry = ToolRegistry(work_dir=str(tmp_path), exec_provider=fake)
        await registry.execute("run_python", {"code": "x = 1", "timeout": -3})
        await registry.execute("run_python", {"code": "x = 1", "timeout": 10**9})
        assert fake.calls[0][1]["timeout"] == 5
        assert fake.calls[1][1]["timeout"] == 600

    @pytest.mark.asyncio
    async def test_non_numeric_timeout_falls_back_to_default(self, tmp_path):
        # 垃圾值不再抛异常走 Error 分支，而是回默认 120（健壮性顺带修复）
        fake = FakeExecProvider()
        registry = ToolRegistry(work_dir=str(tmp_path), exec_provider=fake)
        await registry.execute("bash", {"command": "echo hi", "timeout": "abc"})
        assert fake.calls[0][1]["timeout"] == 120
