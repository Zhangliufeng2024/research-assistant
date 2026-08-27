"""Origin 守卫中间件测试（安全加固）：同源校验拦截跨站请求。

背景：全部端点此前无 Origin 校验，浏览器恶意页面可以
- 跨站 WebSocket 直连 /ws/* 驱动本地 agent；
- 用 text/plain 简单请求绕过 CORS 预检调用 POST 接口。

覆盖四类入口 × 错误/正确/缺失三种 Origin 形态：
- HTTP GET（普通 API）；
- HTTP POST text/plain（简单请求，不触发预检的攻击面）；
- WebSocket 握手（须在握手前拒绝）；
- 静态挂载（StaticFiles 也必须被保护）。

不跑 create_app()（lifespan 重，含技能装配与 sqlite）；把生产同款
OriginGuardMiddleware 以 create_app 相同的方式 add_middleware 到裸 app 上，
验证对 http / websocket 两种 scope 与静态挂载的行为。
"""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI, Request, WebSocket  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from research_assistant.web.app import (  # noqa: E402
    OriginGuardMiddleware,
    _same_origin,
    _split_host_port,
)

#: 测试端口模拟 desktop.py 的「127.0.0.1 + 随机端口」绑定形态。
HOST_PORT = "127.0.0.1:8765"
GOOD_ORIGIN = f"http://{HOST_PORT}"
EVIL_ORIGIN = "http://evil.example"


def _make_app(tmp_path) -> FastAPI:
    """裸 app + 生产同款中间件（安装方式与 create_app 一致）。"""
    app = FastAPI()
    app.add_middleware(OriginGuardMiddleware)

    @app.get("/api/ping")
    async def ping():
        return {"ok": True}

    @app.post("/api/approvals/{approval_id}/resolve")
    async def resolve(approval_id: str, request: Request):
        await request.body()  # 消费 body，模拟真实端点
        return {"ok": True, "id": approval_id}

    @app.websocket("/ws/chat")
    async def ws_chat(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"type": "connected"})
        await websocket.close()

    # 静态挂载也走同一守卫（生产挂 "/"，这里挂根目录等价）
    app.mount("/", StaticFiles(directory=str(tmp_path), html=True),
              name="static")
    return app


def _make_client(app: FastAPI) -> TestClient:
    """Host 头固定为 127.0.0.1:<port>，与桌面壳同源场景一致。"""
    return TestClient(app, base_url=f"http://{HOST_PORT}")


@pytest.fixture()
def client(tmp_path):
    with _make_client(_make_app(tmp_path)) as c:
        yield c


# ---------------------------------------------------------------------------
# HTTP GET
# ---------------------------------------------------------------------------


class TestHttpGetOrigin:
    def test_without_origin_allowed(self, client):
        """无 Origin 放行：curl / TestClient / 桌面壳首航不带该头。"""
        assert client.get("/api/ping").status_code == 200

    def test_same_origin_allowed(self, client):
        r = client.get("/api/ping", headers={"Origin": GOOD_ORIGIN})
        assert r.status_code == 200

    def test_loopback_alias_same_port_allowed(self, client):
        """localhost 与 127.0.0.1 同为回环别名，端口一致即放行。"""
        r = client.get("/api/ping", headers={"Origin": "http://localhost:8765"})
        assert r.status_code == 200

    def test_cross_origin_rejected(self, client):
        assert client.get(
            "/api/ping", headers={"Origin": EVIL_ORIGIN}).status_code == 403

    def test_wrong_port_rejected(self, client):
        """回环 host 但端口不符：本机其它服务的页面同样不可信。"""
        assert client.get(
            "/api/ping",
            headers={"Origin": "http://127.0.0.1:9999"}).status_code == 403


# ---------------------------------------------------------------------------
# HTTP POST text/plain（简单请求绕预检的攻击面）
# ---------------------------------------------------------------------------


class TestHttpPostOrigin:
    def _post(self, client, origin):
        headers = {"Content-Type": "text/plain"}
        if origin is not None:
            headers["Origin"] = origin
        return client.post("/api/approvals/a1/resolve", content="{}",
                           headers=headers)

    def test_without_origin_allowed(self, client):
        assert self._post(client, None).status_code == 200

    def test_same_origin_allowed(self, client):
        assert self._post(client, GOOD_ORIGIN).status_code == 200

    def test_cross_origin_simple_request_rejected(self, client):
        """text/plain 不触发 CORS 预检——守卫必须在应用逻辑前拦截。"""
        assert self._post(client, EVIL_ORIGIN).status_code == 403


# ---------------------------------------------------------------------------
# WebSocket 握手
# ---------------------------------------------------------------------------


class TestWsOrigin:
    def test_without_origin_allowed(self, client):
        # 注意 websocket_connect 的 base 硬编码 ws://testserver，
        # 必须传绝对 URL 才能让 Host 头与桌面壳一致。
        with client.websocket_connect(
                f"ws://{HOST_PORT}/ws/chat") as ws:
            assert ws.receive_json() == {"type": "connected"}

    def test_same_origin_allowed(self, client):
        with client.websocket_connect(
                f"ws://{HOST_PORT}/ws/chat",
                headers={"Origin": GOOD_ORIGIN}) as ws:
            assert ws.receive_json() == {"type": "connected"}

    def test_cross_origin_closed_before_handshake(self, client):
        """跨站 WS 在握手前直接关闭，永远拿不到 connected 帧。"""
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                    f"ws://{HOST_PORT}/ws/chat",
                    headers={"Origin": EVIL_ORIGIN}):
                pass  # pragma: no cover - 不应进入会话
        assert exc_info.value.code == 1008

    def test_wrong_port_closed(self, client):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                    f"ws://{HOST_PORT}/ws/chat",
                    headers={"Origin": "http://127.0.0.1:9999"}):
                pass  # pragma: no cover - 不应进入会话
        assert exc_info.value.code == 1008


# ---------------------------------------------------------------------------
# 静态挂载
# ---------------------------------------------------------------------------


class TestStaticMountOrigin:
    def test_static_get_without_origin_allowed(self, tmp_path, client):
        (tmp_path / "index.html").write_text("<html></html>",
                                             encoding="utf-8")
        assert client.get("/index.html").status_code == 200

    def test_static_cross_origin_rejected(self, tmp_path, client):
        (tmp_path / "index.html").write_text("<html></html>",
                                             encoding="utf-8")
        assert client.get(
            "/index.html", headers={"Origin": EVIL_ORIGIN}).status_code == 403


# ---------------------------------------------------------------------------
# 纯函数单测：端口/主机解析边界
# ---------------------------------------------------------------------------


class TestSameOriginUnit:
    def test_https_default_ports_match(self):
        assert _same_origin("https://127.0.0.1", "127.0.0.1", "https")

    def test_scheme_default_port_used_when_host_has_none(self):
        # http 默认 80：origin 缺省端口 vs Host 缺省端口 → 相等放行
        assert _same_origin("http://localhost", "localhost", "http")
        # origin 显式 :8080 vs Host 无端口（按 http 默认 80）→ 不等拒绝
        assert not _same_origin("http://127.0.0.1:8080", "127.0.0.1", "http")

    def test_non_loopback_origin_rejected_even_if_port_matches(self):
        assert not _same_origin("http://evil.example:8765",
                                "127.0.0.1:8765", "http")

    def test_null_and_garbage_origins_rejected(self):
        for bad in ("null", "", "not a url", "ftp://127.0.0.1:8765"):
            assert not _same_origin(bad, HOST_PORT, "http"), repr(bad)

    def test_out_of_range_port_rejected_without_raising(self):
        # .port 属性对越界端口抛 ValueError：守卫必须拒绝而非 500
        assert not _same_origin("http://127.0.0.1:99999",
                                "127.0.0.1:8765", "http")

    def test_malformed_url_rejected_without_raising(self):
        assert not _same_origin("http://[::1", HOST_PORT, "http")

    def test_ipv6_bracketed_origin_and_host(self):
        assert _same_origin("http://[::1]:8000", "[::1]:8000", "http")
        assert not _same_origin("http://[::1]:8000", "[::1]:9000", "http")


class TestSplitHostPortUnit:
    def test_plain_host_with_port(self):
        assert _split_host_port("127.0.0.1:8765") == ("127.0.0.1", 8765)

    def test_host_without_port_returns_none(self):
        assert _split_host_port("testserver") == ("testserver", None)

    def test_ipv6_bracketed(self):
        assert _split_host_port("[::1]:8000") == ("::1", 8000)
        assert _split_host_port("[::1]") == ("::1", None)

    def test_empty_header(self):
        assert _split_host_port("") == (None, None)
