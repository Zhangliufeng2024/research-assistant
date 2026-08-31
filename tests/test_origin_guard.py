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
    TOKEN_HEADER,
    TOKEN_QUERY_PARAM,
    OriginGuardMiddleware,
    TokenInjectingStatic,
    _extract_token,
    _same_origin,
    _split_host_port,
    generate_api_token,
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


# ---------------------------------------------------------------------------
# P1-3 本地 API token
# ---------------------------------------------------------------------------


def _make_token_app(tmp_path, token: str | None) -> FastAPI:
    """裸 app + 生产同款中间件；token 显式注入（不跑 lifespan）。"""
    app = FastAPI()
    app.add_middleware(OriginGuardMiddleware)
    # 显式设置（含空串）——未设属性 = 未启用，正是既有测试的形态
    if token is not None:
        app.state.api_token = token

    @app.get("/api/ping")
    async def ping():
        return {"ok": True}

    @app.websocket("/ws/chat")
    async def ws_chat(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"type": "connected"})
        await websocket.close()

    app.mount("/", StaticFiles(directory=str(tmp_path), html=True), name="static")
    return app


class TestApiTokenEnforcement:
    """token 已配置：/api 与 /ws 必须携带；静态资源免检。"""

    @pytest.fixture()
    def client(self, tmp_path):
        token = generate_api_token()
        with TestClient(
            _make_token_app(tmp_path, token), base_url=f"http://{HOST_PORT}"
        ) as c:
            c.ra_token = token  # type: ignore[attr-defined]
            yield c

    def test_api_without_token_rejected(self, client):
        assert client.get("/api/ping").status_code == 401

    def test_api_with_correct_header_allowed(self, client):
        r = client.get("/api/ping", headers={TOKEN_HEADER: client.ra_token})
        assert r.status_code == 200

    def test_api_with_bearer_allowed(self, client):
        r = client.get(
            "/api/ping", headers={"Authorization": f"Bearer {client.ra_token}"},
        )
        assert r.status_code == 200

    def test_api_with_wrong_token_rejected(self, client):
        r = client.get("/api/ping", headers={TOKEN_HEADER: "not-the-token"})
        assert r.status_code == 401

    def test_static_path_exempt(self, tmp_path, client):
        """静态资源必须免检——否则 UI 自身都加载不了。"""
        (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
        assert client.get("/index.html").status_code == 200
        assert client.get("/").status_code == 200

    def test_ws_without_token_closed(self, client):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"ws://{HOST_PORT}/ws/chat"):
                pass
        assert exc_info.value.code == 1008

    def test_ws_with_query_token_allowed(self, client):
        """浏览器无法给 WS 设自定义头 → 查询串是唯一携带方式。"""
        with client.websocket_connect(
            f"ws://{HOST_PORT}/ws/chat?{TOKEN_QUERY_PARAM}={client.ra_token}"
        ) as ws:
            assert ws.receive_json() == {"type": "connected"}

    def test_ws_with_wrong_query_token_closed(self, client):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                f"ws://{HOST_PORT}/ws/chat?{TOKEN_QUERY_PARAM}=wrong"
            ):
                pass
        assert exc_info.value.code == 1008


class TestApiTokenDisabled:
    """token 未配置：行为与修复前完全一致（既有测试与开发态的兼容承诺）。"""

    @pytest.fixture()
    def client(self, tmp_path):
        with TestClient(
            _make_token_app(tmp_path, None), base_url=f"http://{HOST_PORT}"
        ) as c:
            yield c

    def test_api_allowed_without_token(self, client):
        assert client.get("/api/ping").status_code == 200

    def test_ws_allowed_without_token(self, client):
        with client.websocket_connect(f"ws://{HOST_PORT}/ws/chat") as ws:
            assert ws.receive_json() == {"type": "connected"}

    def test_empty_token_string_disables_enforcement(self, tmp_path):
        """显式空串 = 未启用（lifespan 在 RA_DISABLE_API_TOKEN 下即如此）。"""
        with TestClient(
            _make_token_app(tmp_path, ""), base_url=f"http://{HOST_PORT}"
        ) as client:
            assert client.get("/api/ping").status_code == 200


class TestApiTokenInjection:
    """TokenInjectingStatic：token 只随入口 HTML 下发一次。"""

    def _wrap(self, tmp_path, token):
        static = StaticFiles(directory=str(tmp_path), html=True)
        return TokenInjectingStatic(static, tmp_path / "index.html")

    def test_index_html_gets_injected(self, tmp_path):
        (tmp_path / "index.html").write_text(
            "<html><head></head><body></body></html>", encoding="utf-8"
        )
        token = generate_api_token()
        app = FastAPI()
        app.state.api_token = token
        app.mount("/", self._wrap(tmp_path, token))
        with TestClient(app) as client:
            html = client.get("/").text
        assert f'window.__RA_API_TOKEN__="{token}"' in html
        assert html.index("__RA_API_TOKEN__") < html.index("</head>")

    def test_other_assets_untouched(self, tmp_path):
        (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
        (tmp_path / "app.js").write_text("console.log(1)", encoding="utf-8")
        app = FastAPI()
        app.state.api_token = generate_api_token()
        app.mount("/", self._wrap(tmp_path, token=app.state.api_token))
        with TestClient(app) as client:
            assert client.get("/app.js").text == "console.log(1)"

    def test_injection_failure_falls_back_to_static(self, tmp_path):
        """入口文件读不到时必须退回静态挂载，绝不能让 UI 打不开。"""
        missing = tmp_path / "index.html"  # 不创建
        app = FastAPI()
        app.state.api_token = generate_api_token()
        app.mount("/", TokenInjectingStatic(
            StaticFiles(directory=str(tmp_path), html=True), missing,
        ))
        with TestClient(app) as client:
            # StaticFiles 对缺失 index 返回 404 而非 500——这就是「不因注入失败挂掉」
            assert client.get("/").status_code == 404

    def test_no_store_cache_header(self, tmp_path):
        """token 不能落浏览器缓存（缓存的旧页面会带着旧 token）。"""
        (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
        app = FastAPI()
        app.state.api_token = generate_api_token()
        app.mount("/", self._wrap(tmp_path, app.state.api_token))
        with TestClient(app) as client:
            assert client.get("/").headers.get("cache-control") == "no-store"


class TestApiTokenUnit:
    def test_token_is_url_safe_and_long(self):
        token = generate_api_token()
        assert len(token) >= 32
        assert all(c.isalnum() or c in "-_" for c in token)
        assert generate_api_token() != generate_api_token()

    def test_extract_token_header(self):
        scope = {
            "type": "http",
            "headers": [(b"x-ra-token", b"abc123")],
        }
        assert _extract_token(scope) == "abc123"

    def test_extract_token_bearer(self):
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer tok-9")],
        }
        assert _extract_token(scope) == "tok-9"

    def test_extract_token_prefers_explicit_header(self):
        scope = {
            "type": "http",
            "headers": [
                (b"authorization", b"Bearer from-bearer"),
                (b"x-ra-token", b"from-header"),
            ],
        }
        assert _extract_token(scope) == "from-header"

    def test_extract_token_ws_query(self):
        scope = {"type": "websocket", "query_string": b"session=a&token=tok-7"}
        assert _extract_token(scope) == "tok-7"

    def test_extract_token_missing(self):
        assert _extract_token({"type": "http", "headers": []}) == ""
        assert _extract_token({"type": "websocket", "query_string": b""}) == ""


class TestLifespanTokenGeneration:
    """lifespan 会生成 token；RA_DISABLE_API_TOKEN 可显式关闭。"""

    def test_lifespan_generates_token(self, tmp_path, monkeypatch, isolated_appdata):
        from research_assistant.web.app import create_app

        # isolated_appdata 必须有：lifespan 会跑 load_project_env，它把
        # **真实的全局配置**（%APPDATA%）以 override=True 灌进 os.environ。
        # 不隔离的话，机器上若设过 RA_PERMISSION_MODE=off，就会泄漏到
        # 本文件之后的测试（实测让 test_policy_blocks_through_agent_loop
        # 的策略挂载失效）——这是跨测试状态污染，不是产品缺陷。
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("", encoding="utf-8")
        app = create_app()
        with TestClient(app):
            token = getattr(app.state, "api_token", "")
            assert token, "lifespan 必须生成 token（生产入口依赖它）"
            assert client_gets_protected(app, token)

    def test_lifespan_disable_env(self, tmp_path, monkeypatch, isolated_appdata):
        from research_assistant.web.app import create_app

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RA_DISABLE_API_TOKEN", "1")
        app = create_app()
        with TestClient(app):
            assert getattr(app.state, "api_token", "") == ""


def client_gets_protected(app: FastAPI, token: str) -> bool:
    """辅助断言：生成 token 后 /api 确实被守卫保护。"""
    client = TestClient(app)
    return client.get("/api/settings").status_code == 401
