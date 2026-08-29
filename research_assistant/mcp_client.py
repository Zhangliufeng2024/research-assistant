"""G-2：MCP（Model Context Protocol）客户端 — stdio 子进程接入。

实现 MCP 规范 2024-11-05 基础子集：JSON-RPC 2.0 over stdio。
- ``McpServerConnection``：管理单个 stdio 子进程，握手（initialize →
  notifications/initialized）后可 tools/list / tools/call。
- ``connect_mcp_servers``：批量连接并把远端工具包装成 ``ToolExtension``
  注册进 ``ToolRegistry``（工具名加 ``mcp_<server>_<tool>`` 前缀防冲突）。
- ``parse_servers_config``：解析 RA_MCP_SERVERS 环境变量（容错）。

已知限制：仅支持 stdio 传输与文本内容结果（不做 SSE/HTTP、图片/资源）。
"""

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from .tools.registry import ToolExtension, ToolRegistry

logger = logging.getLogger(__name__)

#: 本客户端支持并协商的 MCP 协议版本（2024-11-05 基础子集）
MCP_PROTOCOL_VERSION = "2024-11-05"

_DEFAULT_STARTUP_TIMEOUT_S = 15.0
_DEFAULT_REQUEST_TIMEOUT_S = 30.0
_CLOSE_GRACE_TIMEOUT_S = 3.0


class McpServerError(RuntimeError):
    """MCP 服务器连接或调用失败（启动失败/协议错误/进程退出/超时）。"""


class McpProtocolError(McpServerError):
    """协议层失败：版本不匹配、响应格式非法等。"""


class McpServerConnection:
    """一个 MCP stdio 子进程的连接。

    请求-响应按自增 id 匹配（asyncio.Future 表）；通知分发给回调；
    子进程意外退出时挂起请求立即报错（不挂死）。
    """

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        *,
        env: dict[str, str] | None = None,
        startup_timeout: float = _DEFAULT_STARTUP_TIMEOUT_S,
        request_timeout: float = _DEFAULT_REQUEST_TIMEOUT_S,
    ):
        self.name = name
        self.command = command
        self.args = list(args or [])
        self.env = env
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._next_id = 1
        self._reader_task: asyncio.Task[None] | None = None
        #: 读循环读到 EOF（子进程退出）后置 True，之后的请求直接报错
        self._eof = False
        self._notification_handlers: dict[str, list[Callable[[dict], None]]] = {}
        self.server_info: dict[str, Any] = {}
        self.protocol_version: str | None = None

    # ---- 连接 / 握手 ---------------------------------------------------

    async def connect(self) -> "McpServerConnection":
        """启动子进程并完成 initialize 握手。

        子进程启动失败或握手失败时清理资源后抛出 ``McpServerError``。
        """
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=self.env,
            )
        except (OSError, ValueError) as e:
            raise McpServerError(
                f"MCP 服务器 {self.name!r} 启动失败（command={self.command!r}）: {e}"
            ) from e
        self._reader_task = asyncio.create_task(self._read_loop())
        try:
            await self._initialize()
        except Exception:
            await self.close()
            raise
        return self

    async def _initialize(self) -> None:
        """initialize（版本协商 + capability 交换）→ notifications/initialized。"""
        result = await asyncio.wait_for(
            self._request(
                "initialize",
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "research-assistant", "version": "3.5.0"},
                },
            ),
            timeout=self.startup_timeout,
        )
        if not isinstance(result, dict):
            raise McpProtocolError(f"MCP 服务器 {self.name!r} initialize 响应非法")
        server_version = result.get("protocolVersion")
        if server_version != MCP_PROTOCOL_VERSION:
            raise McpProtocolError(
                f"MCP 服务器 {self.name!r} 协议版本不匹配: "
                f"server={server_version!r}, client={MCP_PROTOCOL_VERSION!r}"
            )
        self.protocol_version = server_version
        self.server_info = result.get("serverInfo") or {}
        # 通知（无 id）：客户端已完成初始化
        await self._notify("notifications/initialized")

    # ---- 请求 / 通知 ---------------------------------------------------

    async def _request(self, method: str, params: dict[str, Any]) -> Any:
        """发送一条 JSON-RPC 请求并等待按 id 匹配的响应。"""
        proc = self._proc
        if proc is None or self._eof or proc.returncode is not None:
            raise McpServerError(f"MCP 服务器 {self.name!r} 已退出，无法发送 {method!r}")
        rid = self._next_id
        self._next_id += 1
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[rid] = future
        try:
            await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            return await asyncio.wait_for(future, timeout=self.request_timeout)
        except asyncio.TimeoutError:
            raise McpServerError(
                f"MCP 服务器 {self.name!r} 请求 {method!r} 超时（{self.request_timeout}s）"
            ) from None
        finally:
            self._pending.pop(rid, None)

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """发送一条 JSON-RPC 通知（无 id，服务器不回包）。"""
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        await self._send(message)

    async def _send(self, message: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise McpServerError(f"MCP 服务器 {self.name!r} stdin 不可用")
        line = json.dumps(message, ensure_ascii=False) + "\n"
        try:
            proc.stdin.write(line.encode("utf-8"))
            await proc.stdin.drain()
        except (OSError, ValueError) as e:
            raise McpServerError(f"MCP 服务器 {self.name!r} 写入失败: {e}") from e

    async def _read_loop(self) -> None:
        """逐行读取 stdout 并分发：按 id 唤醒 Future，通知走回调。"""
        assert self._proc is not None and self._proc.stdout is not None
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break  # EOF：子进程退出
                self._dispatch(line.decode("utf-8", errors="replace"))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 读管道异常等价于连接不可用
            pass
        finally:
            self._eof = True
            # 子进程退出：所有挂起请求立即失败，调用方感知而非挂死
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(
                        McpServerError(f"MCP 服务器 {self.name!r} 意外退出，请求未完成")
                    )

    def _dispatch(self, line: str) -> None:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(message, dict):
            return
        if "id" not in message:
            # 通知：分发给已注册的回调
            method = message.get("method")
            for handler in self._notification_handlers.get(method, []):
                try:
                    handler(message)
                except Exception:  # noqa: BLE001 — 通知回调失败不影响主循环
                    logger.debug("MCP 通知回调失败 method=%s", method, exc_info=True)
            return
        future = self._pending.get(message.get("id"))
        if future is None or future.done():
            return
        if "error" in message:
            error = message["error"] or {}
            future.set_exception(McpServerError(
                f"MCP 服务器 {self.name!r} 返回错误: "
                f"{error.get('code')} {error.get('message')}"
            ))
        else:
            future.set_result(message.get("result"))

    def on_notification(self, method: str, handler: Callable[[dict], None]) -> None:
        """注册通知回调（如 notifications/tools/list_changed）。"""
        self._notification_handlers.setdefault(method, []).append(handler)

    # ---- MCP 方法 ------------------------------------------------------

    async def list_tools(self) -> list[dict[str, Any]]:
        """tools/list：返回远端工具描述列表（name/description/inputSchema）。"""
        result = await self._request("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            raise McpProtocolError(f"MCP 服务器 {self.name!r} tools/list 响应非法")
        return [tool for tool in tools if isinstance(tool, dict)]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """tools/call：调用远端工具，把文本内容拼接为字符串返回。"""
        result = await self._request(
            "tools/call", {"name": name, "arguments": dict(arguments or {})},
        )
        if not isinstance(result, dict):
            raise McpProtocolError(f"MCP 服务器 {self.name!r} tools/call 响应非法")
        if result.get("isError"):
            raise McpServerError(f"MCP 工具 {name!r} 调用失败: {result.get('content')}")
        parts: list[str] = []
        for item in result.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts)

    # ---- 关闭 ----------------------------------------------------------

    async def close(self) -> None:
        """终止子进程并回收资源（异常路径也可安全调用，幂等）。

        关闭顺序：EOF 唤醒挂起请求 → 关 stdin（礼貌退出）→ 等待 →
        terminate → 等待 → kill 兜底（Windows 下 terminate 即强杀，
        kill 兜底覆盖其余平台上的悬挂情况）。
        """
        self._eof = True
        for future in self._pending.values():
            if not future.done():
                future.set_exception(McpServerError(f"MCP 服务器 {self.name!r} 已关闭"))
        self._pending.clear()
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 — 回收路径尽力而为
                pass
            self._reader_task = None
        proc = self._proc
        if proc is not None:
            self._proc = None
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except Exception:  # noqa: BLE001
                    pass
            if proc.returncode is None:
                try:
                    await asyncio.wait_for(proc.wait(), timeout=_CLOSE_GRACE_TIMEOUT_S)
                except asyncio.TimeoutError:
                    pass
            if proc.returncode is None:
                try:
                    proc.terminate()
                except (ProcessLookupError, OSError):
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=_CLOSE_GRACE_TIMEOUT_S)
                except asyncio.TimeoutError:
                    pass
            if proc.returncode is None:
                try:
                    proc.kill()
                except (ProcessLookupError, OSError):
                    pass
                try:
                    await proc.wait()
                except Exception:  # noqa: BLE001
                    pass


def _sanitize_name_part(raw: str) -> str:
    """把服务器/工具名规整为工具名安全片段（空格等替换为下划线）。"""
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in raw).strip("_") or "srv"


def _make_tool_handler(conn: McpServerConnection, remote_name: str) -> Callable[..., Awaitable[str]]:
    """生成 ToolExtension 的 handler：转发 arguments → 拼接文本结果。"""

    async def handler(**kwargs: Any) -> str:
        return await conn.call_tool(remote_name, kwargs)

    handler.__name__ = f"mcp_tool_{_sanitize_name_part(remote_name)}"
    return handler


async def connect_mcp_servers(
    registry: ToolRegistry, servers: list[dict[str, Any]],
) -> list[McpServerConnection]:
    """批量连接 MCP 服务器并把其工具注册进 registry。

    每项形如 ``{"name": str, "command": str, "args": [...]}``。
    部分可用优于全或无：单个服务器失败（启动/握手/列工具）只记录告警并
    继续下一个；名称冲突的服务器跳过并告警。返回成功连接的连接清单
    （调用方负责在会话结束时 close）。
    """
    connections: list[McpServerConnection] = []
    used_names: set[str] = set()
    for spec in servers:
        if not isinstance(spec, dict):
            logger.warning("MCP 配置项非法（非对象），已跳过: %r", spec)
            continue
        name = str(spec.get("name") or "").strip()
        command = str(spec.get("command") or "").strip()
        if not name or not command:
            logger.warning("MCP 配置项缺少 name/command，已跳过: %r", spec)
            continue
        if name in used_names:
            logger.warning("MCP 服务器名称冲突（%s），后者已跳过", name)
            continue
        used_names.add(name)
        args = spec.get("args") or []
        if not isinstance(args, list):
            args = [str(arg) for arg in args if arg is not None]
        conn = McpServerConnection(name, command, [str(arg) for arg in args])
        try:
            await conn.connect()
            tools = await conn.list_tools()
        except Exception as e:  # noqa: BLE001 — 单个服务器失败不中断其它
            logger.warning("MCP 服务器 %s 接入失败，已跳过: %s", name, e)
            await conn.close()
            continue
        registered = 0
        for tool in tools:
            remote_name = str(tool.get("name") or "").strip()
            if not remote_name:
                continue
            ext_name = f"mcp_{_sanitize_name_part(name)}_{_sanitize_name_part(remote_name)}"
            if ext_name in registry.extensions:
                logger.warning("MCP 工具 %s 与已有工具冲突，已跳过", ext_name)
                continue
            schema = tool.get("inputSchema")
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            extension = ToolExtension(
                name=ext_name,
                description=str(tool.get("description") or f"MCP 工具 {remote_name}"),
                schema=schema,
                handler=_make_tool_handler(conn, remote_name),
            )
            try:
                registry.register_extension(extension)
            except ValueError as e:
                logger.warning("MCP 工具 %s 注册失败，已跳过: %s", ext_name, e)
                continue
            registered += 1
        logger.info("MCP 服务器 %s 接入完成，注册 %d 个工具", name, registered)
        connections.append(conn)
    return connections


def parse_servers_config(raw: str) -> list[dict[str, Any]]:
    """解析 RA_MCP_SERVERS 环境变量（JSON 数组）。

    容错：空串/空白/非法 JSON/非数组 → 空列表；数组内缺少 name 或
    command 的条目丢弃并告警。
    """
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("RA_MCP_SERVERS 非法 JSON，按空配置处理: %s", e)
        return []
    if not isinstance(data, list):
        logger.warning("RA_MCP_SERVERS 不是 JSON 数组，按空配置处理")
        return []
    servers: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip() \
                or not str(item.get("command") or "").strip():
            logger.warning("RA_MCP_SERVERS 条目缺少 name/command，已跳过: %r", item)
            continue
        servers.append(item)
    return servers


def connect_mcp_servers_sync(
    registry: ToolRegistry, servers: list[dict[str, Any]],
) -> list[McpServerConnection]:
    """同步包装：供无事件循环的调用点使用（内部自建 asyncio.run）。"""
    return asyncio.run(connect_mcp_servers(registry, servers))


def get_env_servers() -> list[dict[str, Any]]:
    """读取 RA_MCP_SERVERS 环境变量并解析为服务器配置列表。"""
    return parse_servers_config(os.getenv("RA_MCP_SERVERS", ""))
