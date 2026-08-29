"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..artifacts import ArtifactVersionStore
from ..config import (
    app_config_env_path,
    ensure_global_config,
    load_project_env,
    resolve_model,
)
from ..context import SourceStore
from ..core import ensure_output_folder, setup_claude_skills
from ..runtime import BackgroundTaskHub, DurableScheduler, PlatformStore, build_scheduler_dispatcher
from ..tools.citation_verify import close_shared_clients

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 同源守卫（安全加固）：单点收口，覆盖 /api、/ws 与静态挂载
# ---------------------------------------------------------------------------

#: 允许的 Origin 主机白名单：桌面壳与真实浏览器 E2E 都走回环地址。
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
#: scheme → 默认端口（Origin 或 Host 缺省端口时按此兜底）。
_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}


def _split_host_port(host_header: str) -> tuple[str | None, int | None]:
    """拆 Host 头为 ``(主机, 端口)``；缺省端口返回 ``None`` 由调用方兜底。"""
    host_header = (host_header or "").strip()
    if not host_header:
        return None, None
    if host_header.startswith("["):  # IPv6 带方括号：[::1]:8000
        host, _, rest = host_header[1:].partition("]")
        if rest.startswith(":") and rest[1:].isdigit():
            return host.lower(), int(rest[1:])
        return host.lower(), None
    if host_header.count(":") > 1:  # 裸 IPv6（规范要求方括号，此处兜底）
        return host_header.strip("[]").lower(), None
    host, sep, port = host_header.rpartition(":")
    if sep and port.isdigit():
        return host.lower(), int(port)
    return host_header.lower(), None


def _same_origin(origin: str, host_header: str, request_scheme: str) -> bool:
    """判断 *origin* 是否与本次请求同源（回环主机 + 端口一致）。"""
    try:
        parts = urlsplit(origin)
    except ValueError:  # 畸形 URL（如 "http://[::1"）：一律拒绝
        return False
    # hostname 已小写并去掉 IPv6 方括号；scheme 仅接受 http/https。
    if parts.scheme not in ("http", "https"):
        return False
    origin_host = parts.hostname
    if origin_host is None or origin_host not in _LOOPBACK_HOSTS:
        return False
    try:  # 越界端口（如 :99999）的 .port 访问会抛 ValueError：按拒绝处理
        origin_port = parts.port or _DEFAULT_PORTS[parts.scheme]
    except ValueError:
        return False
    _, request_port = _split_host_port(host_header)
    if request_port is None:
        request_port = _DEFAULT_PORTS.get(request_scheme)
    return origin_port == request_port


async def _reject_http(send: Any) -> None:
    """纯 ASGI 地回一个 403 文本响应。"""
    body = b"cross-origin request rejected"
    await send({
        "type": "http.response.start",
        "status": 403,
        "headers": [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"content-length", str(len(body)).encode("ascii")),
        ],
    })
    await send({"type": "http.response.body", "body": body})


async def _reject_websocket(send: Any) -> None:
    """握手前拒绝：发送 websocket.close（uvicorn 会以 HTTP 403 回绝握手）。"""
    await send({"type": "websocket.close", "code": 1008,
                "reason": "origin rejected"})


class OriginGuardMiddleware:
    """纯 ASGI 同源守卫中间件：同时拦截 http 与 websocket 两种 scope。

    背景：本地 agent 的全部端点若不做 Origin 校验，浏览器恶意页面可以
    - 经跨站 WebSocket 直连 /ws/* 驱动本地 agent；
    - 用 text/plain「简单请求」绕过 CORS 预检调用 POST 接口。
    因此在 create_app 单点收口（本类包住整个路由栈，含静态挂载），规则：

    - 无 Origin 头 → 放行（curl / TestClient / 桌面壳同源 GET 通常不带）；
    - 有 Origin → 解析其 host 与 port：host 必须 ∈ 回环白名单，port 必须等于
      本次请求 Host 头的端口（Host 缺省端口按 scheme 默认端口处理），
      匹配才放行；否则 http scope 回 403，websocket scope 在握手前关闭。

    注意不能用 BaseHTTPMiddleware——它不拦截 websocket scope。
    desktop.py 随机端口绑定 127.0.0.1，页面与 WS 天然同源，不受影响。
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)  # lifespan 等：直通
            return
        origin = host = ""
        for key, value in scope.get("headers") or []:
            name = key.decode("latin-1").lower()
            if name == "origin":
                origin = value.decode("latin-1")
            elif name == "host":
                host = value.decode("latin-1")
        if not origin or _same_origin(origin, host, scope.get("scheme") or "http"):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http":
            await _reject_http(send)
        else:
            await _reject_websocket(send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cwd = Path.cwd().resolve()
    ensure_global_config(cwd)  # 老工作区 .env 配置一次性上移到全局（R8）
    load_project_env(cwd)

    package_dir = Path(__file__).parent.parent.absolute()
    setup_claude_skills(package_dir, cwd)

    app.state.cwd = cwd
    app.state.output_folder = ensure_output_folder(cwd)
    # 设置页存储位置：全局配置文件（切换工作目录不丢，R8 反馈 #1 配套）。
    # 测试可覆写 app.state.env_file 指向临时目录。
    app.state.env_file = app_config_env_path()
    app.state.model = resolve_model()
    app.state.active_tasks = {}
    # Platform state is intentionally stored inside the workspace so a project
    # remains portable.  The task hub owns execution; WebSockets only observe.
    platform_store = PlatformStore(cwd / ".ra" / "platform.sqlite3")
    platform_store.mark_orphaned_running_tasks()
    app.state.platform_store = platform_store
    app.state.project = platform_store.ensure_project(cwd)
    app.state.task_hub = BackgroundTaskHub(platform_store)
    app.state.scheduler = DurableScheduler(platform_store, janitor_cwd=cwd)
    app.state.source_store = SourceStore(cwd / ".ra" / "sources.sqlite3")

    # A+ 阶段 1 / F-1 存量修复：F-1 修复前，Janitor 淘汰快照 .bin 时并不改
    # 索引，老工作区里因此可能残留一批「索引说有、磁盘没有」的悬空记录——
    # 点「恢复」会删掉用户当前的真实文件。启动时把这类记录显性标记为已清理，
    # 之后 UI 会禁用恢复入口、restore 也改为报 409 而非删文件。
    #
    # 幂等、且只在确有不一致时才回写 index.json；失败不得阻断启动。
    try:
        reconciled = ArtifactVersionStore(cwd).reconcile_snapshots()
        if reconciled:
            LOG.info("版本快照索引修复：标记 %d 条快照缺失的变更记录", reconciled)
    except Exception:  # noqa: BLE001 — 启动路径绝不能因治理逻辑失败而中断
        LOG.warning("版本快照索引修复失败（不影响启动）", exc_info=True)

    dispatchers, _dispatch = build_scheduler_dispatcher(
        store=platform_store,
        hub=app.state.task_hub,
        cwd=cwd,
        project=app.state.project,
        source_store=app.state.source_store,
        default_model=app.state.model,
    )
    for workflow_id, dispatcher in dispatchers.items():
        app.state.scheduler.register(workflow_id, dispatcher)
    # The queue is a first-class runtime now: scheduled jobs continue even if
    # the browser WebSocket disconnects.  FastAPI lifespan guarantees cleanup.
    app.state.scheduler.start()
    try:
        yield
    finally:
        await app.state.scheduler.stop()
        await close_shared_clients()


def create_app() -> FastAPI:
    app = FastAPI(title="研究助手", lifespan=lifespan)

    # 同源守卫最先注册：包住全部路由（含下方静态挂载），见类注释。
    app.add_middleware(OriginGuardMiddleware)

    from .chat import router as chat_router
    from .routes import router as api_router
    from .settings import router as settings_router
    from .workspace import router as workspace_router
    from .ws import router as ws_router

    app.include_router(api_router, prefix="/api")
    app.include_router(workspace_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    # chat 挂两次：REST 走 /api 前缀；/ws/chat 由前端硬编码，需再裸挂一次（见 protocol.md §10）
    app.include_router(chat_router, prefix="/api")
    app.include_router(chat_router)
    app.include_router(ws_router)

    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
