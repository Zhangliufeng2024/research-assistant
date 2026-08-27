"""R14 real-browser smoke: new shell + chat WS round-trip against a mock LLM.

Run from the repository root after ``cd frontend; npm run build``::

    python scripts/e2e_smoke_r14.py

Covers this round's risk surface (App shell rewrite / ChatView rewiring /
SessionList rewrite / stream coalescing): first-run wizard, 6-item nav, a
REAL WebSocket chat turn (the exact blind spot that let the R7-R9 ws.ts bug
escape three rounds of protocol-level tests), message actions, session
search/rename, grouped-page tabs and Ctrl+K search.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[1]
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

APP_PORT = 18801
MOCK_PORT = 18802
BASE = f"http://127.0.0.1:{APP_PORT}"

REPLY = "冒烟通过：这是来自 mock 模型的回复 R14-SMOKE-OK"
NAV_LABELS = ["总览", "会话", "任务中心", "研究工作台", "资料库", "设置"]


def _require_free_port(port: int, name: str) -> None:
    """残留监听会让请求打到旧进程，断言静默假绿（harness 坑④）——先占位探测。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(f"{name} 端口 {port} 已被占用：{exc}") from exc


class _MockLLMHandler(BaseHTTPRequestHandler):
    """OpenAI 兼容假端点：流式 SSE 吐一段固定文本后 DONE。"""

    #: 收到的请求记录；收尾断言非空——防止静默回落到真机配置打真实 API
    hits: list[str] = []

    def do_POST(self):  # noqa: N802 (http.server 接口)
        length = int(self.headers.get("Content-Length") or 0)
        self.hits.append(self.path)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            body = {}
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()

            def _chunk(payload: dict) -> None:
                self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())

            _chunk({"id": "cm-mock", "choices": [{"index": 0, "delta": {"role": "assistant", "content": REPLY}}]})
            _chunk({"id": "cm-mock", "choices": [{"index": 0, "delta": {}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8}})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            payload = {
                "id": "cm-mock", "choices": [{"index": 0, "message": {"role": "assistant", "content": REPLY}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8},
            }
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def log_message(self, *args):  # 静默
        return


def start_mock_llm() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), _MockLLMHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    if not EDGE.is_file():
        raise RuntimeError(f"Edge executable not found: {EDGE}")
    _require_free_port(APP_PORT, "app")
    _require_free_port(MOCK_PORT, "mock-llm")

    root = Path(tempfile.mkdtemp(prefix="ra-smoke-r14-"))
    server = None
    mock = None
    try:
        mock = start_mock_llm()
        env = os.environ.copy()
        # 关键隔离：APPDATA 指向临时目录。config.load_project_env 会以
        # %APPDATA%/ResearchAssistant/.env 的托管键终局裁决压掉注入的
        # LLM_* 环境变量（override=True）——不隔离就会用本机真实 Key 打
        # 真实 API，冒烟静默变真调用。
        (root / "appdata").mkdir()
        env.update({
            "PYTHONPATH": str(REPO),
            "APPDATA": str(root / "appdata"),
            "LLM_API_KEY": "sk-mock-smoke",
            "LLM_BASE_URL": f"http://127.0.0.1:{MOCK_PORT}/v1",
            "LLM_MODEL": "mock-model",
            "LLM_PROVIDER": "openai",
        })
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "research_assistant.web.app:create_app",
             "--factory", "--host", "127.0.0.1", "--port", str(APP_PORT), "--log-level", "error"],
            cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE), args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    if page.request.get(f"{BASE}/api/status", timeout=2000).ok:
                        break
                except Exception:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("server did not become ready")

            # --- 新壳层启动 + 首启向导 ---
            page.goto(f"{BASE}/#/", wait_until="domcontentloaded")
            expect(page.get_by_text("配置模型 API", exact=True)).to_be_visible(timeout=15000)
            page.get_by_role("button", name="开始使用").click()
            expect(page.get_by_text("配置模型 API", exact=True)).to_have_count(0)

            # 向导关闭持久化：刷新不再出现
            page.reload(wait_until="domcontentloaded")
            expect(page.get_by_text("配置模型 API", exact=True)).to_have_count(0)

            # --- 侧栏恰好六项 ---
            nav = page.locator("aside nav a")
            expect(nav).to_have_count(len(NAV_LABELS))
            for label in NAV_LABELS:
                expect(page.locator("aside nav a", has_text=label)).to_have_count(1)

            # --- 真实 WS 聊天往返（核心断言）---
            page.goto(f"{BASE}/#/chat", wait_until="domcontentloaded")
            composer = page.get_by_placeholder("输入消息，与助手讨论…")
            expect(composer).to_be_visible(timeout=10000)
            composer.fill("这是一条冒烟测试消息")
            page.get_by_role("button", name="发送消息").click()
            expect(page.get_by_text(REPLY, exact=True)).to_be_visible(timeout=30000)

            # --- 消息操作三件套：复制 + 重新生成 ---
            # （R16 真替换语义：旧回答随 truncate 从对话流移除后重发——mock 每次
            # 返回同一文本，故可见气泡数恒为 1；旧断言「出现 2 条」编码的是已
            # 废除的追加式平行答案行为。）
            assistant_bubble = page.locator("div.group", has=page.get_by_text(REPLY, exact=True)).first
            assistant_bubble.hover()
            assistant_bubble.get_by_role("button", name="复制").click()
            expect(page.get_by_text("已复制", exact=True)).to_be_visible()
            assistant_bubble.get_by_role("button", name="重新生成").click()
            expect(page.get_by_text(REPLY, exact=True)).to_have_count(1, timeout=30000)

            # --- 会话列表：出现、搜索过滤、重命名（列表列容器 bg-canvas，区别于壳层侧栏 bg-rail）---
            session_list = page.locator("div.w-60.bg-canvas")
            session_row = session_list.locator("div.group", has_text="这是一条冒烟测试消息").first
            expect(session_row).to_be_visible(timeout=15000)
            search = page.get_by_label("搜索会话")
            search.fill("zzz-no-match")
            expect(page.get_by_text("无匹配会话", exact=True)).to_be_visible()
            search.fill("")
            expect(session_row).to_be_visible()

            session_row.hover()
            session_row.locator('button[title="重命名"]').click()
            rename_input = page.get_by_label("重命名会话")
            expect(rename_input).to_be_visible()
            rename_input.fill("冒烟改名后的会话")
            rename_input.press("Enter")
            expect(session_list.get_by_text("冒烟改名后的会话", exact=True)).to_be_visible(timeout=10000)

            # --- 聚合页二级 tab 条 ---
            page.goto(f"{BASE}/#/tasks", wait_until="domcontentloaded")
            queue_tab = page.get_by_role("link", name="运行队列")
            expect(queue_tab).to_be_visible()
            queue_tab.click()
            page.wait_for_url("**/#/scheduler", timeout=10000)
            expect(page.get_by_role("link", name="任务", exact=True)).to_be_visible()

            # --- Ctrl+K 全局搜索 ---
            page.keyboard.press("Control+k")
            expect(page.get_by_placeholder("搜索项目对象…")).to_be_visible()

            # mock 必须被真实命中：若为空说明后端绕过注入配置打了真 API
            assert _MockLLMHandler.hits, "mock LLM 未被调用——后端疑似使用了本机真实配置"
            print(f"[mock-hits] {len(_MockLLMHandler.hits)} request(s)")

            print("[UI-E2E-SMOKE-R14] PASS")
            browser.close()
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        if mock is not None:
            mock.shutdown()
            mock.server_close()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
