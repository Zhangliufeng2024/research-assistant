"""R16 real-browser smoke: 耐久化回合（断连回放）+ 真替换 + 附件全链路。

Run from the repository root after ``cd frontend; npm run build``::

    python scripts/e2e_smoke_r16.py

覆盖本轮风险面（正是让 ws.ts 一行缺失连逃三轮的盲区类别——协议级测试
mock 掉了真实浏览器时序，必须真浏览器验证）：

1. **断连不杀回合 + attach 后直播尾流**：回合中途用第二个 WS 客户端抢占
   同一会话（服务端按「后连者踢前者」close 4001），断言前端进入自动重连
   横幅；剩余流刻意在**观察到 attach 发出之后**才放行——尾流必须以直播
   形式路由到新 socket（只测快照回放抓不住发射绑死旧 socket 的缺陷）；
   最终回答恰好一个气泡且无重复。
2. **重新生成 = 真替换**：旧回答从对话流消失（truncate），而非追加
   「平行答案」；原提问保留且只出现一次。带附件的提问重新生成后，
   附件引用必须随重发入史（不得断链）。
3. **附件链路**：📎 选择文件 → chip 上屏 → 随消息入史（REST history 带
   attachments）→ 刷新后历史恢复含附件徽章。
"""

from __future__ import annotations

import json
import os
import re
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
from websockets.sync.client import connect as ws_connect

REPO = Path(__file__).resolve().parents[1]
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

APP_PORT = 18803
MOCK_PORT = 18804
BASE = f"http://127.0.0.1:{APP_PORT}"

NAV_LABELS = ["总览", "会话", "任务中心", "研究工作台", "资料库", "设置"]

#: 流被闸门扣住时先吐的前半段；放行后再吐的后半段（两段拼成完整回答）
HALF1_TAIL = "·"
HALF2 = "次应答"

#: mock 端点收到的请求数（线程安全由 GIL 保证的列表 append）
GATE = threading.Event()


def _require_free_port(port: int, name: str) -> None:
    """残留监听会让请求打到旧进程，断言静默假绿（harness 坑④）——先占位探测。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(f"{name} 端口 {port} 已被占用：{exc}") from exc


class _MockLLMHandler(BaseHTTPRequestHandler):
    """OpenAI 兼容假端点。

    应答回显最后一条用户消息并带请求序号（每次调用内容必不同）：
    ``收到[<用户消息>]·第<N>次应答``。流式路径受 GATE 控制——先吐前半段，
    GATE 关闭时阻塞在后半段之前，用于构造「回合运行中被断连」的窗口。
    """

    hits: list[str] = []

    def do_POST(self):  # noqa: N802 (http.server 接口)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            body = {}
        self.hits.append(self.path)
        n = len(self.hits)
        last_user = ""
        for m in reversed(body.get("messages") or []):
            if isinstance(m, dict) and m.get("role") == "user":
                last_user = str(m.get("content") or "")
                break
        full = f"收到[{last_user}]{HALF1_TAIL}第{n}{HALF2}"
        half1 = f"收到[{last_user}]{HALF1_TAIL}"
        half2 = f"第{n}{HALF2}"

        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()

            def _chunk(payload: dict) -> None:
                self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
                self.wfile.flush()

            _chunk({"id": "cm-mock", "choices": [{"index": 0, "delta": {"role": "assistant", "content": half1}}]})
            if not GATE.is_set():
                GATE.wait(90)  # 扣住流：给测试留出「断连」窗口
            _chunk({"id": "cm-mock", "choices": [{"index": 0, "delta": {"content": half2}}]})
            _chunk({"id": "cm-mock", "choices": [{"index": 0, "delta": {}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8}})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            payload = {
                "id": "cm-mock",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": full}}],
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


def _short(payload: object) -> str:
    """WS 帧摘要：文本截断到 120 字符，二进制只报长度。"""
    text = payload if isinstance(payload, str) else repr(payload)
    return text[:120].replace("\n", " ")


#: 浏览器发出的全部 WS 帧（诊断 + 断言「重连后确实发了 attach」）
SENT_FRAMES: list[str] = []

#: 服务端 stdout 行（后台线程持续收集；失败时倒出来看——uvicorn 以
#: --log-level error 跑，异常栈只在 stderr/stdout，PIPE 不读就永远看不见）
SERVER_LOG: list[str] = []


def _drain_server_log(proc: subprocess.Popen) -> None:
    """后台线程：把服务端进程输出逐行收进 SERVER_LOG（防 PIPE 塞满阻塞）。"""
    raw = proc.stdout
    if raw is None:
        return
    for line in iter(raw.readline, b""):
        try:
            SERVER_LOG.append(line.decode("utf-8", errors="replace").rstrip())
        except Exception:
            break


def main() -> None:
    if not EDGE.is_file():
        raise RuntimeError(f"Edge executable not found: {EDGE}")
    _require_free_port(APP_PORT, "app")
    _require_free_port(MOCK_PORT, "mock-llm")

    root = Path(tempfile.mkdtemp(prefix="ra-smoke-r16-"))
    attach_path = root / "冒烟附件.txt"
    attach_path.write_text("R16 附件冒烟内容\n", encoding="utf-8")

    server = None
    mock = None
    try:
        GATE.set()  # Event 初始为未置位：默认放行流，仅在「断连窗口」场景显式 clear
        mock = start_mock_llm()
        env = os.environ.copy()
        # APPDATA 隔离同 R14：托管键会压掉注入的 LLM_*，不隔离就打真 API
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
        threading.Thread(target=_drain_server_log, args=(server,), daemon=True).start()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE), args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            # 诊断探针：WS 生命周期与帧序（断连回放是否真的发生、attach 发了什么）
            page.on("websocket", lambda ws: (
                print(f"[ws+] {ws.url}"),
                ws.on("close", lambda w: print(f"[ws-x] {w.url}")),
                ws.on(
                    "framesent",
                    lambda p: (
                        SENT_FRAMES.append(str(p)),
                        print(f"[ws>] {_short(p)}"),
                    ),
                ),
                ws.on("framereceived", lambda p: print(f"[ws<] {_short(p)}")),
            ))
            page.on("console", lambda m: print(f"[console] {m.type}: {m.text}") if m.type in ("error", "warning") else None)
            # 未捕获异常（含 setTimeout 回调里的 throw）只有这里看得见——
            # 上一轮重连静默失败时诊断盲区正是缺了这只眼睛
            page.on(
                "pageerror",
                lambda e: print(f"[pageerror] {type(e).__name__}: {e}"),
            )
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

            # --- 启动 + 首启向导 ---
            page.goto(f"{BASE}/#/", wait_until="domcontentloaded")
            expect(page.get_by_text("配置模型 API", exact=True)).to_be_visible(timeout=15000)
            page.get_by_role("button", name="开始使用").click()
            expect(page.get_by_text("配置模型 API", exact=True)).to_have_count(0)

            nav = page.locator("aside nav a")
            expect(nav).to_have_count(len(NAV_LABELS))

            # --- 会话页：第一轮（GATE 开）---
            page.goto(f"{BASE}/#/chat", wait_until="domcontentloaded")
            composer = page.get_by_placeholder("输入消息，与助手讨论…")
            expect(composer).to_be_visible(timeout=10000)
            composer.fill("第一问")
            page.get_by_role("button", name="发送消息").click()
            rx_first = re.compile(r"^收到\[第一问\]·第\d+次应答$")
            expect(page.get_by_text(rx_first)).to_be_visible(timeout=30000)

            def session_id() -> str:
                res = page.request.get(f"{BASE}/api/chat/sessions")
                data = res.json()
                rows = data if isinstance(data, list) else data.get("sessions") or []
                assert rows, "sessions 列表为空"
                return rows[0]["id"]

            # --- 第二轮：GATE 关，扣住流制造「回合运行中」窗口 ---
            GATE.clear()
            composer.fill("第二问")
            page.get_by_role("button", name="发送消息").click()
            rx_half1 = re.compile(r"^收到\[第二问\]·$")
            expect(page.get_by_text(rx_half1)).to_be_visible(timeout=30000)

            # 抢占连接：服务端「后连者踢前者」，浏览器 socket 被 close 4001；
            # 回合本身不受影响（R16 核心契约）。抢完立刻退出让位给重连。
            sid = session_id()
            with ws_connect(f"ws://127.0.0.1:{APP_PORT}/ws/chat?session={sid}", open_timeout=10) as rogue:
                rogue.recv(timeout=5)  # connected 帧
            print("[kick] rogue client attached and left")

            # 前端感知断线 → 自动重连横幅（非致命警示，不是错误态）
            expect(page.get_by_text("正在自动重连", exact=False)).to_be_visible(timeout=15000)

            # 等重连后的 attach 真正发出（回放窗口闭合），**然后**才放行剩余流。
            # 顺序是刻意的回归设计：此前 GATE 先开、尾流在重连完成前已全部
            # 入环形缓冲，attach 只测到「快照回放」；现在「后半/usage/result」
            # 必须以直播形式路由到重连后的新 socket——发射路径绑死旧 socket
            # 的缺陷（attach 只补快照、尾流进尸体连接）只有这个顺序能抓出。
            deadline = time.time() + 25
            while time.time() < deadline:
                if any('"action":"attach"' in f for f in SENT_FRAMES):
                    break
                time.sleep(0.1)
            else:
                # 诊断三连：浏览器帧、服务端日志、以及旁路探针——用第二个
                # python 客户端连同一会话。探针能连上是服务端正常（问题在
                # 浏览器侧重连机器）；连不上是服务端拒新连接。
                probe_status = "未执行"
                try:
                    with ws_connect(
                        f"ws://127.0.0.1:{APP_PORT}/ws/chat?session={sid}",
                        open_timeout=5,
                    ) as probe:
                        probe.recv(timeout=3)
                        probe_status = "可连接（服务端接受新连接）"
                except Exception as exc:  # noqa: BLE001
                    probe_status = f"失败：{type(exc).__name__}: {exc}"
                raise AssertionError(
                    "重连后未发出 attach 帧：\n"
                    f"  SENT_FRAMES={SENT_FRAMES}\n"
                    f"  探针：{probe_status}\n"
                    "  服务端日志尾部：\n    "
                    + "\n    ".join(SERVER_LOG[-30:])
                )

            # 放行剩余流：attach 之后的直播尾流必须到达新 socket
            GATE.set()
            rx_second = re.compile(r"^收到\[第二问\]·第\d+次应答$")
            expect(page.get_by_text(rx_second)).to_be_visible(timeout=20000)
            # 完整回答恰好一个气泡（半段不得重复成两条）
            expect(page.get_by_text(rx_second)).to_have_count(1)
            # 横幅退场：重连成功后警示消失
            expect(page.get_by_text("正在自动重连", exact=False)).to_have_count(0, timeout=15000)
            # 绝不能出现「放弃重连」的危险横幅
            expect(page.get_by_text("未能自动恢复", exact=False)).to_have_count(0)

            # --- 重新生成 = 真替换：旧回答整体消失，新回答顶替其位 ---
            old_answer = page.get_by_text(rx_second).text_content() or ""
            bubble = page.locator("div.group", has=page.get_by_text(rx_second)).first
            bubble.hover()
            bubble.get_by_role("button", name="重新生成").click()
            # 同一提问再次应答 → 序号递增，文本必然不同
            expect(page.get_by_text(old_answer, exact=True)).to_have_count(0, timeout=30000)
            expect(page.get_by_text(rx_second)).to_have_count(1)
            new_answer = page.get_by_text(rx_second).text_content() or ""
            assert new_answer != old_answer, "重新生成未产生新应答（假替换）"
            # 原提问保留且只此一份（不得因截断/重发出现双气泡）
            expect(page.get_by_text("第二问", exact=True)).to_have_count(1)

            # --- 附件链路：选择 → chip → 随消息入史 ---
            with page.expect_file_chooser() as fc_info:
                page.get_by_role("button", name="添加附件").click()
            fc_info.value.set_files(str(attach_path))
            expect(page.get_by_text("冒烟附件.txt", exact=True)).to_be_visible(timeout=10000)

            composer.fill("第三问带附件")
            page.get_by_role("button", name="发送消息").click()
            rx_third = re.compile(r"^收到\[第三问带附件\]·第\d+次应答$")
            expect(page.get_by_text(rx_third)).to_be_visible(timeout=30000)

            detail = page.request.get(
                f"{BASE}/api/chat/sessions/{sid}"
            ).json()
            msgs = detail.get("messages") or []
            print("[hist-tail]", json.dumps(msgs[-4:], ensure_ascii=False))
            assert msgs[-2].get("role") == "user", "倒数第二条应为 user 条目"
            atts = msgs[-2].get("attachments") or []
            assert atts and atts[0].get("name") == "冒烟附件.txt", (
                f"user 条目缺 attachments：{msgs[-2]}"
            )
            uploads_dir = Path(atts[0]["path"])
            assert uploads_dir.is_file(), f"上传文件未落盘：{uploads_dir}"

            # --- 真替换保全附件：对带附件的提问重新生成，附件引用不得断链。
            # （truncate 会把带附件的旧 user 条目整条删掉，重发若不显式携带
            # 原附件，「读一下我传的数据」类追问在新回合就无数据可读了。） ---
            old_third = page.get_by_text(rx_third).text_content() or ""
            bubble3 = page.locator("div.group", has=page.get_by_text(rx_third)).first
            bubble3.hover()
            bubble3.get_by_role("button", name="重新生成").click()
            expect(page.get_by_text(old_third, exact=True)).to_have_count(
                0, timeout=30000
            )
            expect(page.get_by_text(rx_third)).to_have_count(1)
            detail2 = page.request.get(f"{BASE}/api/chat/sessions/{sid}").json()
            msgs2 = detail2.get("messages") or []
            atts2 = (msgs2[-2] or {}).get("attachments") or []
            assert atts2 and atts2[0].get("name") == "冒烟附件.txt", (
                f"重新生成后附件断链：{msgs2[-2]}"
            )
            assert Path(atts2[0]["path"]).is_file(), "重发引用的上传文件丢失"
            print("[atts-keep] regenerate preserved attachment ref")

            # --- 刷新：应用不自动恢复会话（空白草稿态）→ 从列表重开本会话，
            # REST 历史应恢复完整对话流，附件徽章仍在 ---
            page.reload(wait_until="domcontentloaded")
            expect(page.get_by_placeholder("输入消息，与助手讨论…")).to_be_visible(
                timeout=15000
            )
            session_list = page.locator("div.w-60.bg-canvas")
            session_list.locator("div.group", has_text="第一问").first.click()
            expect(page.get_by_text(rx_third)).to_be_visible(timeout=15000)
            expect(page.get_by_text("冒烟附件.txt", exact=True)).to_be_visible()
            expect(page.get_by_text(rx_first)).to_be_visible()
            expect(page.get_by_text(rx_second)).to_be_visible()

            assert _MockLLMHandler.hits, "mock LLM 未被调用——后端疑似使用了本机真实配置"
            print(f"[mock-hits] {len(_MockLLMHandler.hits)} request(s)")
            print("[UI-E2E-SMOKE-R16] PASS")
            browser.close()
    finally:
        GATE.set()  # 兜底放行，避免残留线程阻塞进程退出
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
