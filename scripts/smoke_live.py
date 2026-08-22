"""全量在线冒烟（人工运维工具——会真实调用 LLM 产生费用，勿入 CI）：静态资源 + REST 全端点 + 双 WS 通道 + 真实一轮对话 + 受控生成/停止。

运行：PYTHONIOENCODING=utf-8 python scripts/smoke_live.py
"""
import asyncio
import json
import re
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote

import uvicorn

from research_assistant.web.app import create_app

PORT = 8833
app = create_app()
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(60):
    if server.started:
        break
    time.sleep(0.2)

B = f"http://127.0.0.1:{PORT}"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    mark = "PASS " if cond else "FAIL "
    line = mark + name
    if not cond and detail:
        line += " | " + str(detail)[:200]
    print(line, flush=True)


def req(method, path, body=None, raw=False, timeout=15):
    r = urllib.request.Request(
        B + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            data = resp.read()
            if raw:
                return resp.status, data, resp.headers
            return resp.status, (json.loads(data) if data else None), resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200], e.headers
    except Exception as e:
        return 0, str(e).encode()[:200], {}


import websockets  # noqa: E402

# ============ 1. 静态资源（React 构建产物，R7 起） ============
s, html, _ = req("GET", "/", raw=True)
check("static index.html",
      s == 200 and b'id="root"' in html[:4000] and b"/assets/index-" in html[:4000],
      f"status={s}")

_m_js = re.search(rb'src="(/assets/index-[^"]+\.js)"', html or b"")
_m_css = re.search(br'href="(/assets/index-[^"]+\.css)"', html or b"")
check("static app bundle", bool(_m_js), "index.html 未引用 /assets/index-*.js")
if _m_js:
    s, js, _ = req("GET", _m_js.group(1).decode(), raw=True)
    check("static bundle js", s == 200 and not js.lstrip().startswith(b"<!"), f"status={s}")
check("static bundle css", bool(_m_css), "index.html 未引用 /assets/index-*.css")
if _m_css:
    s, css, _ = req("GET", _m_css.group(1).decode(), raw=True)
    check("static bundle css content", s == 200 and b"--ra-accent" in css, f"status={s}")

# ============ 2. REST ============
s, st, _ = req("GET", "/api/status")
check("status fields", s == 200 and all(k in st for k in
      ("model", "provider", "approval_mode", "permission_mode", "repeat_limit", "version")), st)

s, runs, _ = req("GET", "/api/runs")
check("runs list", s == 200 and isinstance(runs, list), f"n={len(runs) if isinstance(runs, list) else runs}")
if isinstance(runs, list) and runs:
    s, ev, _ = req("GET", f"/api/runs/{quote(runs[0]['name'])}/events?tail=50")
    check("run events", s == 200 and "total" in ev and "events" in ev, ev)

s, papers, _ = req("GET", "/api/papers")
check("papers list", s == 200 and isinstance(papers, list), f"n={len(papers) if isinstance(papers, list) else papers}")
if isinstance(papers, list) and papers:
    name = quote(papers[0]["name"])
    s, p, _ = req("GET", f"/api/papers/{name}")
    check("paper detail", s == 200 and "files" in p)
    s, data, hdr = req("GET", f"/api/papers/{name}/export", raw=True)
    check("paper export zip", s == 200 and data[:2] == b"PK" and "zip" in hdr.get("Content-Type", ""), f"status={s}")

# 工作区
s, ws_info, _ = req("GET", "/api/workspace")
check("workspace card", s == 200 and ws_info.get("has_git") is True)
s, tree, _ = req("GET", "/api/workspace/tree?path=&depth=1")
check("workspace tree", s == 200 and isinstance(tree.get("items"), list) and len(tree["items"]) > 3)
s, tree2, _ = req("GET", "/api/workspace/tree?path=research_assistant&depth=1")
check("workspace subtree", s == 200 and any(i["name"] == "web" for i in tree2.get("items", [])))
s, f1, _ = req("GET", "/api/workspace/file?path=README.md")
check("workspace text preview", s == 200 and f1.get("kind") == "text" and "Research Assistant" in f1.get("content", ""))
s, f2, h2 = req("GET", "/api/workspace/file?path=packaging/app_icon.ico", raw=True)
check("workspace binary attachment", s == 200 and f2[:4] == b"\x00\x00\x01\x00",
      f"status={s} ct={getattr(h2, 'get', lambda *_: '')('Content-Type')}")
s, _, _ = req("GET", "/api/workspace/file?path=..%2F..%2F.env")
check("fence blocks traversal", s == 403, f"status={s}")
s, _, _ = req("POST", "/api/workspace/open?path=.")
check("shell-open gated 403", s == 403, f"status={s}")

# 会话 REST
s, created, _ = req("POST", "/api/chat/sessions", {"title": "smoke"})
sid = quote(created["id"])
check("chat session create", s == 200 and created.get("id"))
s, one, _ = req("GET", f"/api/chat/sessions/{sid}")
check("chat session get", s == 200 and isinstance(one.get("messages"), list))
check("chat session delete", req("DELETE", f"/api/chat/sessions/{sid}")[0] == 200)
check("chat session gone", req("GET", f"/api/chat/sessions/{sid}")[0] == 404)

# ============ 3. WS chat：真实一轮 ============
async def chat_roundtrip():
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/chat") as w:
        f = json.loads(await asyncio.wait_for(w.recv(), 10))
        check("chat ws connected", f.get("type") == "connected" and bool(f.get("session_id")))
        await w.send(json.dumps({"action": "user", "text": "请只回复两个字：收到"}))
        text, got_result, err, saw_usage = "", False, None, False
        try:
            while True:
                m = json.loads(await asyncio.wait_for(w.recv(), 120))
                t = m.get("type")
                if t == "text":
                    text += m.get("delta", "")
                elif t == "usage":
                    saw_usage = True
                elif t == "result":
                    got_result = True
                    break
                elif t == "error":
                    err = m.get("message")
                    break
        except asyncio.TimeoutError:
            err = "120s 无终帧"
        check("chat real round-trip", got_result and bool(text.strip()), f"text={text[:80]!r} err={err}")
        check("chat usage frames", saw_usage)
        return f.get("session_id")


try:
    csid = asyncio.run(chat_roundtrip())
except Exception as e:  # websockets 缺失等
    print("SKIP chat ws:", e)
    csid = None

if csid:
    s, one, _ = req("GET", f"/api/chat/sessions/{quote(csid)}")
    msgs = (one or {}).get("messages", [])
    check("chat history persisted", s == 200 and
          any(m.get("role") == "user" for m in msgs) and any(m.get("role") == "assistant" for m in msgs),
          f"roles={[m.get('role') for m in msgs]}")
    check("chat cleanup delete", req("DELETE", f"/api/chat/sessions/{quote(csid)}")[0] == 200)

# ============ 4. WS generate：受控启动 → 停止 ============
async def generate_bounded():
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/generate") as w:
        # 该端点是 start 驱动：先发 start 再收 connected 回执（与 chat 端点不同，见 protocol.md §5）
        await w.send(json.dumps({
            "action": "start",
            "query": "连通性冒烟：完成规划阶段即可，不要撰写正文。",
            "multi_agent": False,
            "max_cost_usd": 0.05,
            "track_token_usage": True,
        }))
        f = json.loads(await asyncio.wait_for(w.recv(), 20))
        check("generate ws connected (post-start)", f.get("type") == "connected" and bool(f.get("task_id")), f)
        tid = quote(str(f.get("task_id")))
        saw_progress = saw_usage = cancelled = finished = False
        err = None
        stopped = False
        deadline = time.time() + 150
        try:
            while time.time() < deadline:
                m = json.loads(await asyncio.wait_for(w.recv(), 40))
                t = m.get("type")
                if t == "progress":
                    saw_progress = True
                    if m.get("stage") == "cancelled":
                        cancelled = True
                        break
                elif t == "usage":
                    saw_usage = True
                elif t == "error":
                    err = m.get("message")
                    break
                elif t == "result":
                    finished = True
                    break
        except asyncio.TimeoutError:
            pass
        if not (cancelled or finished or err):
            s, _, _ = req("POST", f"/api/tasks/{tid}/stop", {})
            stopped = s == 200
            try:
                while True:
                    m = json.loads(await asyncio.wait_for(w.recv(), 40))
                    if m.get("type") == "progress" and m.get("stage") == "cancelled":
                        cancelled = True
                        break
                    if m.get("type") in ("result", "error"):
                        break
            except asyncio.TimeoutError:
                pass
        check("generate progress frames", saw_progress)
        check("generate usage ticks", saw_usage)
        check("generate terminal state", cancelled or finished or err,
              f"cancelled={cancelled} finished={finished} err={err}")
        if stopped or cancelled:
            check("generate cancel path", cancelled, "stop 未产生 cancelled 帧" if not cancelled else "")


try:
    asyncio.run(generate_bounded())
except Exception as e:
    print("SKIP generate ws:", e)

server.should_exit = True
fails = [n for n, ok in results if not ok]
print(f"\n==== {len(results) - len(fails)}/{len(results)} PASS ====")
for n in fails:
    print("FAILED:", n)
