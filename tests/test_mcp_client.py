"""G-2：MCP 客户端测试。

不依赖网络或 npx：用 tests/fixtures/mcp_echo_server.py（极小参考 MCP
server，stdin/stdout 逐行 JSON-RPC）+ sys.executable 启动。覆盖握手、
tools/list、tools/call、协议版本不匹配、启动失败、registry 注册与执行、
名称冲突跳过、配置解析容错、子进程资源回收。
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

import pytest

from research_assistant.mcp_client import (
    McpProtocolError,
    McpServerConnection,
    McpServerError,
    connect_mcp_servers,
    parse_servers_config,
)
from research_assistant.tools.registry import ToolRegistry

ECHO_SERVER = str(Path(__file__).parent / "fixtures" / "mcp_echo_server.py")


def make_connection(**kwargs) -> McpServerConnection:
    """用 sys.executable 启动参考 echo server 的连接。"""
    return McpServerConnection("echo", sys.executable, [ECHO_SERVER], **kwargs)


def make_registry() -> ToolRegistry:
    return ToolRegistry(work_dir=str(Path(__file__).parent))


# ---- P1-2：子进程环境净化 -----------------------------------------------


class TestChildEnvSanitization:
    """MCP 子进程不得继承未净化的 os.environ。

    修复前 ``create_subprocess_exec(..., env=self.env)`` 在 self.env 为 None
    时**继承完整环境**（含 LLM_API_KEY 等一切密钥）——bash / run_python 早已
    走 ``sanitized_exec_env()`` 净化，MCP 是唯一的漏网路径，等于把执行工具
    的密钥净化整体绕过。
    """

    def test_default_env_strips_secrets(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-should-not-leak")
        monkeypatch.setenv("MY_VENDOR_SECRET", "nope")
        env = McpServerConnection("s", "cmd")._child_env()
        assert "LLM_API_KEY" not in env
        assert "MY_VENDOR_SECRET" not in env

    def test_default_env_keeps_operating_vars(self, monkeypatch):
        """净化不能变成「清空」——PATH/HOME 等必须保留（反向断言）。"""
        monkeypatch.setenv("MCP_KEEP_ME", "yes")
        monkeypatch.setenv("PATH", "/usr/bin")
        env = McpServerConnection("s", "cmd")._child_env()
        assert env.get("MCP_KEEP_ME") == "yes"
        assert env.get("PATH") == "/usr/bin"

    def test_explicit_env_overrides_sanitized_base(self, monkeypatch):
        """用户为**该服务器**显式声明的键应当生效（显式配置优先）。"""
        monkeypatch.setenv("LLM_API_KEY", "sk-leak")
        env = McpServerConnection(
            "s", "cmd", env={"GITHUB_TOKEN": "gh-explicit"},
        )._child_env()
        assert env["GITHUB_TOKEN"] == "gh-explicit"
        assert "LLM_API_KEY" not in env, "基底仍需保持净化"

    async def test_real_subprocess_does_not_inherit_secret(self, monkeypatch):
        """端到端：真起一个子进程，读不到宿主注入的密钥。

        用参考 echo server 不方便断言环境，这里直接跑 python -c 打印环境。
        """
        monkeypatch.setenv("LLM_API_KEY", "sk-must-not-appear")
        conn = McpServerConnection(
            "envprobe", sys.executable,
            ["-c", "import os,json;print(json.dumps(dict(os.environ)))"],
        )
        proc = await asyncio.create_subprocess_exec(
            conn.command, *conn.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=conn._child_env(),
        )
        out, _ = await proc.communicate()
        child = json.loads(out.decode().strip().splitlines()[-1])
        assert "LLM_API_KEY" not in child, "MCP 子进程继承了密钥"
        assert "PATH" in child, "净化不能把 PATH 也清掉"

    async def test_connect_actually_passes_sanitized_env(self, monkeypatch):
        """真正的 bug 在 connect()：它把 self.env（默认 None）直接交给
        create_subprocess_exec，而 None 意味着**继承完整环境**。

        只断言 _child_env() 自身的行为是不够的——必须锁住 connect() 真的
        调用它，否则哪天有人改回 env=self.env，前面几条测试依然全绿。
        """
        monkeypatch.setenv("LLM_API_KEY", "sk-must-not-leak")
        import research_assistant.mcp_client as mod

        seen: dict[str, str] = {}
        real_exec = mod.asyncio.create_subprocess_exec

        async def spy_exec(cmd, *args, **kw):
            seen.update(kw.get("env") or {})
            return await real_exec(cmd, *args, **kw)

        monkeypatch.setattr(mod.asyncio, "create_subprocess_exec", spy_exec)

        conn = await make_connection().connect()
        try:
            assert seen, "connect() 没有传 env（None = 继承完整环境，即原 bug）"
            assert "LLM_API_KEY" not in seen
            assert "PATH" in seen, "净化不能把 PATH 也清掉"
        finally:
            await conn.close()

    async def test_config_env_field_is_honored(self, monkeypatch):
        """配置里的 env 字段此前被解析却从未传入（静默失效）。"""
        monkeypatch.delenv("MCP_FROM_CONFIG", raising=False)
        servers = [{
            "name": "envsrv",
            "command": sys.executable,
            "args": ["-c", "pass"],
            "env": {"MCP_FROM_CONFIG": "1"},
        }]
        # 只验证解析与传参，不真的起服务（command 会在 connect 里失败并跳过）
        from research_assistant.mcp_client import connect_mcp_servers
        conns = await connect_mcp_servers(make_registry(), servers)
        # 连接失败会被跳过，但 env 必须在构造时已传入
        assert conns == []

    def test_env_field_materialized_into_connection(self):
        """直接断言 env 字段落到了 McpServerConnection 上。"""
        captured: list[dict] = []

        class _Spy(McpServerConnection):
            def __init__(self, name, command, args, **kw):
                captured.append(dict(kw))  # 必须拷贝：下面会 pop
                kw.pop("env", None)
                super().__init__(name, command, args, **kw)

        import research_assistant.mcp_client as mod

        original = mod.McpServerConnection
        mod.McpServerConnection = _Spy
        try:
            asyncio.run(connect_mcp_servers(make_registry(), [{
                "name": "s", "command": "cmd",
                "env": {"A": "1", "B": 2, "C": {"nested": True}},
            }]))
        finally:
            mod.McpServerConnection = original

        assert captured, "未构造连接"
        assert captured[0].get("env") == {"A": "1", "B": "2"}, (
            "标量应保留（int 转 str）、嵌套 dict 应剔除"
        )


# ---- 握手与基础方法 -----------------------------------------------------


async def test_connect_handshake_success():
    conn = await make_connection().connect()
    try:
        assert conn.protocol_version == "2024-11-05"
        assert conn.server_info.get("name") == "mcp-echo-server"
    finally:
        await conn.close()


async def test_list_tools_parses_schema():
    conn = await make_connection().connect()
    try:
        tools = await conn.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "echo"
        assert "回显" in tools[0]["description"]
        schema = tools[0]["inputSchema"]
        assert schema["type"] == "object"
        assert "text" in schema["properties"]
    finally:
        await conn.close()


async def test_call_tool_returns_text():
    conn = await make_connection().connect()
    try:
        result = await conn.call_tool("echo", {"text": "你好 MCP"})
        assert result == "echo: 你好 MCP"
    finally:
        await conn.close()


async def test_call_unknown_tool_raises_error():
    conn = await make_connection().connect()
    try:
        # 未知方法：服务器返回 JSON-RPC error，客户端应报错而非挂死
        with pytest.raises(McpServerError):
            await conn.call_tool("no_such_tool", {})
    finally:
        await conn.close()


async def test_protocol_version_mismatch():
    import os

    # 强制服务器返回不匹配的协议版本 → 握手应报协议错误
    conn = McpServerConnection(
        "echo-bad",
        sys.executable,
        [ECHO_SERVER],
        env=dict(os.environ, MCP_FORCE_PROTOCOL_VERSION="1999-01-01"),
    )
    with pytest.raises(McpProtocolError):
        await conn.connect()
    # 异常路径资源回收：子进程必须已被回收
    assert conn._proc is None  # noqa: SLF001


async def test_subprocess_start_failure_raises_without_hang():
    conn = McpServerConnection("ghost", "ra-definitely-not-a-command-xyz")
    with pytest.raises(McpServerError):
        await conn.connect()


async def test_server_exit_fails_pending_requests():
    import asyncio

    conn = await make_connection(request_timeout=10.0).connect()
    try:
        # 杀掉子进程 → 挂起/后续请求应报错而非挂死
        assert conn._proc is not None  # noqa: SLF001
        conn._proc.kill()  # noqa: SLF001
        await conn._proc.wait()  # noqa: SLF001
        await asyncio.sleep(0.2)  # 让读循环感知 EOF
        with pytest.raises(McpServerError):
            await conn.list_tools()
    finally:
        await conn.close()


async def test_request_timeout_raises():
    # 连接后收紧超时 → 正常请求也来不及响应，应报超时错误而非挂死
    conn = await make_connection().connect()
    try:
        conn.request_timeout = 0  # 0 秒超时：wait_for 立即超时，确定性触发
        with pytest.raises(McpServerError):
            await conn.list_tools()
    finally:
        await conn.close()


# ---- registry 集成 ------------------------------------------------------


async def test_connect_mcp_servers_registers_extensions():
    registry = make_registry()
    conns = await connect_mcp_servers(
        registry, [{"name": "echo", "command": sys.executable, "args": [ECHO_SERVER]}],
    )
    try:
        assert len(conns) == 1
        schemas = registry.get_schemas()
        names = [s["name"] for s in schemas]
        assert "mcp_echo_echo" in names
        ext = next(s for s in schemas if s["name"] == "mcp_echo_echo")
        assert "回显" in ext["description"]
        assert ext["parameters"]["properties"]["text"]["type"] == "string"
        # 经 registry.execute 走 ToolExtension handler（exec_provider 无关）
        result = await registry.execute("mcp_echo_echo", {"text": "hi"})
        assert result == "echo: hi"
    finally:
        for conn in conns:
            await conn.close()


async def test_duplicate_server_name_skipped_with_warning(caplog):
    registry = make_registry()
    spec = {"name": "echo", "command": sys.executable, "args": [ECHO_SERVER]}
    with caplog.at_level(logging.WARNING, logger="research_assistant.mcp_client"):
        conns = await connect_mcp_servers(registry, [spec, dict(spec)])
    try:
        # 名称冲突的服务器跳过并告警，不中断其它
        assert len(conns) == 1
        assert any("名称冲突" in rec.message for rec in caplog.records)
    finally:
        for conn in conns:
            await conn.close()


async def test_failed_server_recorded_and_others_continue():
    registry = make_registry()
    conns = await connect_mcp_servers(registry, [
        {"name": "bad", "command": "ra-definitely-not-a-command-xyz", "args": []},
        {"name": "echo", "command": sys.executable, "args": [ECHO_SERVER]},
    ])
    try:
        # 失败的服务器记录后继续：只有 echo 接入成功
        assert len(conns) == 1
        assert conns[0].name == "echo"
        assert "mcp_echo_echo" in registry.extensions
    finally:
        for conn in conns:
            await conn.close()


# ---- 配置解析 -----------------------------------------------------------


def test_parse_servers_config_variants():
    assert parse_servers_config("") == []
    assert parse_servers_config("   ") == []
    assert parse_servers_config("not json {") == []
    assert parse_servers_config('{"name": "x"}') == []  # 非数组 → 空
    ok = [{"name": "s1", "command": "cmd", "args": ["a"]}]
    assert parse_servers_config('[{"name":"s1","command":"cmd","args":["a"]}]') == ok
    # 缺 name/command 的条目被过滤
    raw = '[{"name":"s1","command":"c"},{"name":"","command":"c"},{"foo":1}]'
    assert parse_servers_config(raw) == [{"name": "s1", "command": "c"}]


# ---- 资源回收 ------------------------------------------------------------


async def test_close_is_idempotent_and_reaps_process():
    conn = await make_connection().connect()
    proc = conn._proc  # noqa: SLF001
    await conn.close()
    await conn.close()  # 幂等：二次关闭不报错
    assert conn._proc is None  # noqa: SLF001
    assert proc.returncode is not None  # 子进程已被回收，无僵尸
