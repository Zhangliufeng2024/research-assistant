"""FastAPI application factory."""

import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

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

# ---------------------------------------------------------------------------
# P1-3 本地 API 启动 token
#
# Origin 守卫只能挡住**浏览器**：任何本机进程都能自己伪造 Origin 头（它只是
# 一个请求头，不是凭证）。于是「无 Origin 即放行」这条规则等于给同机任意
# 脚本开了后门——可以改工作区根、读任意文件、唤起任意程序。
#
# 对策：进程启动时生成一个一次性随机 token，所有 /api 与 /ws 请求必须携带。
# token 只通过入口 HTML 下发给本应用自己的页面（见 ``TokenInjectingStatic``），
# 不写文件、不进 .env、不落日志。
#
# **未配置 token 时中间件完全不生效**：裸 ``FastAPI()`` 的测试与开发态
# uvicorn 都不受影响，这是刻意的兼容设计（生产入口 lifespan 一定会生成）。
# ---------------------------------------------------------------------------

#: 需要校验 token 的路径前缀。静态资源与入口页免检——否则 UI 自身加载不了。
_TOKEN_PROTECTED_PREFIXES = ("/api", "/ws")
#: HTTP 携带方式（二选一）。
TOKEN_HEADER = "x-ra-token"
TOKEN_BEARER_PREFIX = "bearer "
#: WebSocket 无法自定义请求头（浏览器 API 限制）→ 只能走查询串。
TOKEN_QUERY_PARAM = "token"
#: 显式关闭 token（仅供开发/排障）：置为 1 时 lifespan 不生成。
_DISABLE_ENV = "RA_DISABLE_API_TOKEN"


def generate_api_token() -> str:
    """生成一个一次性本地 API token（URL 安全、32 字节熵）。"""
    return secrets.token_urlsafe(32)


def _token_disabled() -> bool:
    return os.getenv(_DISABLE_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _requires_token(scope: dict) -> bool:
    path = scope.get("path") or ""
    return any(path.startswith(prefix) for prefix in _TOKEN_PROTECTED_PREFIXES)


def _extract_token(scope: dict) -> str:
    """按 scope 类型取出调用方提供的 token；缺失返回空串。"""
    if scope["type"] == "websocket":
        query = scope.get("query_string") or b""
        try:
            values = parse_qs(query.decode("latin-1")).get(TOKEN_QUERY_PARAM) or []
        except Exception:  # noqa: BLE001 — 畸形查询串按「未提供」处理
            return ""
        return values[0] if values else ""
    headers = scope.get("headers") or []
    bearer = ""
    for key, value in headers:
        name = key.decode("latin-1").lower()
        if name == TOKEN_HEADER:
            return value.decode("latin-1").strip()
        if name == "authorization":
            raw = value.decode("latin-1").strip()
            if raw.lower().startswith(TOKEN_BEARER_PREFIX):
                bearer = raw[len(TOKEN_BEARER_PREFIX):].strip()
            else:
                bearer = raw
    return bearer


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


async def _reject_http_token(send: Any) -> None:
    """token 校验失败：401（区别于 Origin 的 403，便于排障定位）。"""
    body = b"missing or invalid local API token"
    await send({
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"content-length", str(len(body)).encode("ascii")),
        ],
    })
    await send({"type": "http.response.body", "body": body})


async def _reject_websocket_token(send: Any) -> None:
    await send({"type": "websocket.close", "code": 1008,
                "reason": "missing or invalid token"})


class OriginGuardMiddleware:
    """纯 ASGI 守卫中间件：同源校验 + 本地 API token，覆盖 http 与 websocket。

    背景：本地 agent 的全部端点若不做 Origin 校验，浏览器恶意页面可以
    - 经跨站 WebSocket 直连 /ws/* 驱动本地 agent；
    - 用 text/plain「简单请求」绕过 CORS 预检调用 POST 接口。
    因此在 create_app 单点收口（本类包住整个路由栈，含静态挂载），规则：

    - 无 Origin 头 → 放行（curl / TestClient / 桌面壳同源 GET 通常不带）；
    - 有 Origin → 解析其 host 与 port：host 必须 ∈ 回环白名单，port 必须等于
      本次请求 Host 头的端口（Host 缺省端口按 scheme 默认端口处理），
      匹配才放行；否则 http scope 回 403，websocket scope 在握手前关闭。

    P1-3 追加**本地 API token** 校验（先于 Origin 判定）：

    - 仅当 ``app.state.api_token`` 非空时生效。裸 ``FastAPI()``（测试）与未跑
      lifespan 的嵌入场景不设该属性 → 中间件完全放行，行为与修复前一致；
    - 受保护路径为 ``/api`` 与 ``/ws`` 前缀；静态资源与入口页免检；
    - HTTP 取 ``X-RA-Token`` 头或 ``Authorization: Bearer``；WebSocket 浏览器
      无法自定义头，故取查询串 ``?token=``；
    - 比对用常数时间的 ``compare_digest``，不把 token 写进日志。

    注意不能用 BaseHTTPMiddleware——它不拦截 websocket scope。
    desktop.py 随机端口绑定 127.0.0.1，页面与 WS 天然同源，不受影响。
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)  # lifespan 等：直通
            return

        expected = getattr(getattr(scope.get("app"), "state", None),
                           "api_token", "") or ""
        if expected and _requires_token(scope):
            provided = _extract_token(scope)
            if not secrets.compare_digest(provided, expected):
                if scope["type"] == "http":
                    await _reject_http_token(send)
                else:
                    await _reject_websocket_token(send)
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

    # P1-3：一次性本地 API token。仅在本进程内存中，不落盘、不进 .env。
    # 未配置时守卫中间件完全放行（测试/嵌入场景），生产入口一定生成。
    app.state.api_token = (
        "" if _token_disabled() else generate_api_token()
    )

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
    from .prompt import router as prompt_router
    from .routes import router as api_router
    from .settings import router as settings_router
    from .workspace import router as workspace_router
    from .ws import router as ws_router

    app.include_router(api_router, prefix="/api")
    app.include_router(workspace_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(prompt_router, prefix="/api")
    # chat 挂两次：REST 走 /api 前缀；/ws/chat 由前端硬编码，需再裸挂一次（见 protocol.md §10）
    app.include_router(chat_router, prefix="/api")
    app.include_router(chat_router)
    app.include_router(ws_router)

    static_dir = Path(__file__).parent / "static"
    app.mount(
        "/",
        TokenInjectingStatic(
            StaticFiles(directory=str(static_dir), html=True),
            static_dir / "index.html",
        ),
        name="static",
    )

    return app


class TokenInjectingStatic:
    """静态挂载包装：给入口 HTML 注入一次性本地 API token。

    静态资源本身免检（否则 UI 加载不了），但入口页必须把 token 交给前端——
    浏览器**无法**给 WebSocket 设置自定义请求头，token 只能这样下发到页面，
    再由前端自行附加到 REST 头与 WS 查询串上。

    token 只在**响应入口 HTML 时**注入一次：

    - 不写磁盘、不进 .env、不进构建产物（前端 bundle 里搜不到）；
    - 响应带 ``Cache-Control: no-store``，不落浏览器缓存；
    - 读取入口文件失败时原样退回静态挂载，绝不因此让 UI 打不开。
    """

    #: 需要注入的路径（Vite 产物的入口就是 / 与 /index.html）
    _ENTRY_PATHS = ("/", "/index.html")

    def __init__(self, static: Any, index_path: Path) -> None:
        self._static = static
        self._index_path = index_path

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path") not in self._ENTRY_PATHS:
            await self._static(scope, receive, send)
            return
        token = getattr(getattr(scope.get("app"), "state", None),
                        "api_token", "") or ""
        try:
            html = self._index_path.read_text(encoding="utf-8")
        except OSError:
            await self._static(scope, receive, send)
            return
        body = self._inject(html, token).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"text/html; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _inject(html: str, token: str) -> str:
        snippet = f"<script>window.__RA_API_TOKEN__={json.dumps(token)};</script>"
        if "</head>" in html:
            return html.replace("</head>", snippet + "</head>", 1)
        return snippet + html
