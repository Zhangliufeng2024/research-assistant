"""R2 会话模式后端：会话 REST CRUD + 通用 agentic 会话循环（/ws/chat）。

对应 docs/plans/2026-08-22-desktop-workspace.md §3-R2 C1–C4 与 §2 架构决策
D2（history.json 权威持久化）/ D4（安全基线不放宽）：

- 每个会话一个目录 ``<workdir>/.ra/sessions/<YYYYMMDD_HHMMSS_slug>/``，
  复用 SessionStore 写 run.json（mode="chat"）与 events.jsonl 审计镜像；
- ``history.json`` 是对话的唯一权威持久化（D2）：存归约后的
  ``[{role, content}, ...]`` 文本往来，每轮结束整份写回，重启即恢复；
  events.jsonl 仍只作逐条审计镜像（kernel msg_add），不做重放重建；
- 循环直调内核 ``run_agent(RunConfig)``：模型/provider 经 config 层解析，
  预算经 ``BudgetGuard`` 默认从 RA_MAX_* 环境变量继承；steer / 审批 /
  cancel 的接线方式与 ws.py generate 端点同构；
- 流式文本：run_agent 在传入 on_text 时走流式路径（on_chunk 逐段回调，
  见 agent.py），因此每个文本片段即时推送 {"type":"text", delta} 帧；
- 工具卡片（C4）：on_tool_start 推 running 卡，on_tool_use 回填
  status/result_preview/files。

R16 起回合与连接解耦（耐久化）：断开/刷新只减少观察者计数，运行中的
回合继续跑到终态并把回复全路径落盘（用户消息之后必有 assistant 条目，
取消/失败条目带 ``partial: true``）。重连后发 ``{"action":"attach",
"after":<seq>}`` 从环形缓冲（FRAME_RING_CAP）回放错过的帧；孤儿回合由
看门狗在宽限（RA_CHAT_ORPHAN_GRACE_SECONDS，默认 900s）到期后先协作停
止、再硬取消。历史治理 REST：POST …/truncate 截断、PATCH …/messages/
{i} 改写用户消息、POST …/attachments 上传附件（落 outputs/<sid>/
uploads/，send 时引用校验同一围栏）。

挂载方式（app.py 由主会话完成，本文件不改动它）：REST 需 /api 前缀而
WS 必须落在 /ws/chat（前端 ws.js PATHS.chat 硬编码），因此同一 router
include 两次：

    from .chat import router as chat_router
    app.include_router(chat_router, prefix="/api")   # REST: /api/chat/sessions…
    app.include_router(chat_router)                  # WS:   /ws/chat
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import shutil
import time
import traceback
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from ..agent import RunConfig, run_agent
from ..api import usage_ticks
from ..config import build_llm_client, resolve_model
from ..core import (
    atomic_write_text,
    safe_resolve,
)
from ..kernel.approval import QueueApprover, ToolApprovalRequest
from ..kernel.budget import BudgetGuard
from ..kernel.events import HookBus
from ..kernel.memory import build_memory_store
from ..kernel.tracing import maybe_attach_tracing
from ..session.store import load_run_state as _load_run_state
from ..tools.memory_tools import build_memory_extensions, memory_prompt_section
from ..tools.registry import ToolRegistry
from .chat_history import router as _chat_history_router
from .chat_protocol import (
    COMMAND_HELP_TEXT,
    MAX_STEER_LENGTH,
    MAX_USER_LENGTH,
    OUTBOX_MAXSIZE,
    PREVIEW_LIMIT,
    VISION_IMAGE_MAX_BYTES,  # noqa: F401 — 测试经 chat_mod 读取的兼容再导出
    VISION_MAX_IMAGES,  # noqa: F401 — 测试经 chat_mod 读取的兼容再导出
    _apply_budget_override,
    _budget_limits_summary,
    _chat_system_instructions,
    _content_for_llm,
    _HistoryClient,
    _image_parts_from_entry,
    _is_network_error,
    _jsonable_arguments,
    _outbox_maxsize,  # noqa: F401 — 测试经 chat_mod 读取的兼容再导出
    _planner_instructions,
    _PlannerTools,
    _prepare_attachments,
    _split_slash,
    bounded_put,
    extract_artifact_paths,
)
from .chat_state import (
    _ACTIVE,
    _LIVE,
    _SESSIONS,
    _SINKS,
    _TOMBSTONES,
    DELETE_SETTLE_TIMEOUT_S,
    SessionStore,
    _cwd_of,
    _new_session_dir,
    _outputs_root,
    _read_history,
    _resolve_session_dir,
    _session_summary,
    _sessions_root,
    _sweep_zero_turn_sessions,
    _TurnHandle,
    _valid_session_id,
    _write_history,
)

router = APIRouter()
LOG = logging.getLogger("ra.web.chat")
router.include_router(_chat_history_router)
PLAN_DECISION_TIMEOUT_S = 600.0
@router.post("/chat/sessions")
async def create_session(request: Request):
    """新建会话目录（run.json mode="chat" + 空 history.json），返回名片。"""
    title = ""
    try:  # body 可选：空 body / 非 JSON 一律按无标题处理
        body = await request.json()
        if isinstance(body, dict):
            title = str(body.get("title") or "").strip()[:80]
    except Exception:
        pass

    cwd = _cwd_of(request)
    run_dir = _new_session_dir(_sessions_root(cwd), title)
    store = SessionStore.create(
        run_dir,
        query=title,
        model=resolve_model(None),
        mode="chat",
    )
    store.log_event("session_create", {"title": title})
    _write_history(run_dir, [])
    return {"id": run_dir.name, "created_at": store.state.created_at}
@router.get("/chat/sessions")
async def list_sessions(request: Request):
    """全部会话摘要，按 updated_at 倒序（最近活跃在前）。

    零轮次且超过 ZERO_TURN_TTL_S 的残骸目录先被清退（§6.4）。
    R17：合并 platform_store 的 pinned/archived 标志与派生任务计数——
    置顶会话排在最前（组内仍按 updated_at 倒序），归档标志由前端分组。
    """
    root = _sessions_root(_cwd_of(request))

    def _scan() -> list[dict]:
        # P2-3：目录遍历 + 逐会话读 run.json 必须离开事件循环——会话上百时
        # 这是每次列表刷新都会触发的同步 IO，会把所有 /ws/chat、/ws/generate
        # 的流式帧卡住。flags/counts 此前已经走 to_thread，这里对齐口径。
        # 工程债：零轮次清退（同样遍历目录读 run.json）也放进同一线程，
        # 不再在事件循环上同步跑一遍。
        _sweep_zero_turn_sessions(root, _outputs_root(_cwd_of(request)))
        items: list[dict] = []
        if root.is_dir():
            for child in sorted(root.iterdir()):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                if _load_run_state(child) is None:
                    continue  # 无 run.json 的杂散目录不算会话
                try:
                    items.append(_session_summary(child))
                except OSError:
                    continue  # 并发删除等竞态：跳过即可
        return items

    items = await asyncio.to_thread(_scan)
    store = getattr(request.app.state, "platform_store", None)
    if store is not None and items:
        ids = [str(item["id"]) for item in items]
        flags = await asyncio.to_thread(store.get_session_flags_map, ids)
        counts = await asyncio.to_thread(store.count_tasks_for_sessions, ids)
        for item in items:
            meta = flags.get(str(item["id"])) or {}
            item["pinned"] = bool(meta.get("pinned"))
            item["archived"] = bool(meta.get("archived"))
            item["derived_run_count"] = int(counts.get(str(item["id"])) or 0)
    else:
        for item in items:
            item.setdefault("pinned", False)
            item.setdefault("archived", False)
            item.setdefault("derived_run_count", 0)
    items.sort(
        key=lambda item: (not item.get("pinned"), -(item.get("updated_at") or 0)),
    )
    return items
def _platform_of(request: Request):
    """platform_store + project_id（无库降级 None，与 routes.py 口径一致）。"""
    store = getattr(request.app.state, "platform_store", None)
    project = getattr(request.app.state, "project", None) or {}
    return store, project.get("id")
@router.post("/chat/sessions/{session_id}/flags")
async def set_session_flags(session_id: str, request: Request):
    """R17：设置会话置顶/归档标志（持久在 platform.sqlite3，跨端可见）。

    归档此前只写 localStorage（ra.archived-sessions.v1），换浏览器即丢；
    本端点是唯一权威写入口。会话目录本身必须存在（防给杂散 id 立档）。
    """
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict) or (
        body.get("pinned") is None and body.get("archived") is None
    ):
        raise HTTPException(status_code=422, detail="需要 pinned 或 archived 字段")
    try:
        _resolve_session_dir(_cwd_of(request), session_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="会话 ID 不合法") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    store, _ = _platform_of(request)
    if store is None:
        raise HTTPException(status_code=503, detail="平台存储不可用")
    pinned = body.get("pinned")
    archived = body.get("archived")
    result = await asyncio.to_thread(
        store.set_session_flags,
        session_id,
        pinned=None if pinned is None else bool(pinned),
        archived=None if archived is None else bool(archived),
    )
    return {"ok": True, **result}
PROMOTE_CONTEXT_MESSAGES = 20
PROMOTE_CONTEXT_CHARS = 6000
@router.post("/chat/sessions/{session_id}/promote")
async def promote_session_to_task(session_id: str, request: Request):
    """R17：把当前对话转为后台任务（对话→任务互链的核心入口）。

    打包最近对话上下文进任务 query，任务携 source_session_id 落库——
    任务详情可回链本会话，会话列表显示派生任务徽标。执行走既有
    scheduler 队列（workflow 默认 single，与后台任务同一条耐久链路）。
    """
    try:
        body = await request.json()
    except Exception:
        body = None
    body = body if isinstance(body, dict) else {}
    try:
        run_dir = _resolve_session_dir(_cwd_of(request), session_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="会话 ID 不合法") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    store, project_id = _platform_of(request)
    if store is None or not project_id:
        raise HTTPException(status_code=503, detail="平台存储不可用")

    state = _load_run_state(run_dir) or {}
    title = str(state.get("query") or session_id).strip()
    messages = _read_history(run_dir)
    tail = messages[-PROMOTE_CONTEXT_MESSAGES:]
    context_parts: list[str] = []
    budget = PROMOTE_CONTEXT_CHARS
    for msg in reversed(tail):  # 从最近往回装，预算用尽即止
        role = "用户" if msg["role"] == "user" else "助手"
        chunk = f"{role}: {msg['content'].strip()[:500]}"
        if budget - len(chunk) < 0:
            break
        context_parts.append(chunk)
        budget -= len(chunk)
    context_parts.reverse()
    context_block = "\n".join(context_parts)

    goal = str(body.get("prompt") or "").strip()[:MAX_USER_LENGTH]
    workflow_id = str(body.get("workflow_id") or "single").strip() or "single"
    if goal:
        query = goal
    else:
        query = f"继续完成会话「{title[:60]}」中的工作"
    if context_block:
        query += (
            "\n\n[来源对话上下文（节选，仅供参考，勿逐条回复）]\n"
            f"{context_block}"
        )
    job = await asyncio.to_thread(
        store.enqueue_job,
        project_id=project_id,
        workflow_id=workflow_id,
        payload={"query": query, "source_session_id": session_id},
    )
    return {"ok": True, "job_id": job.get("id"), "workflow_id": workflow_id}
MANIFEST_MAX_FILES = 500
MANIFEST_NAME = "manifest.json"
def _scan_outputs_for_manifest(outputs_dir: Path) -> list[dict[str, Any]]:
    """递归扫描会话产物目录，返回清单条目（mtime 倒序，截 MANIFEST_MAX_FILES）。"""
    entries: list[dict[str, Any]] = []
    for p in outputs_dir.rglob("*"):
        if not p.is_file() or p.name == MANIFEST_NAME:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        rel = p.relative_to(outputs_dir).as_posix()
        entries.append({
            "path": rel,
            "name": p.name,
            "ext": p.suffix.lower(),
            "size": st.st_size,
            "mtime": st.st_mtime,
        })
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return entries[:MANIFEST_MAX_FILES]
@router.get("/chat/sessions/{session_id}/manifest")
async def get_session_manifest(session_id: str, request: Request):
    """迭代2：会话产物清单（懒生成 + 落盘 manifest.json + 回填 artifacts 索引）。

    清单是产物级检索（/api/search?scope=artifacts）的数据源；每次调用都
    重建（产物是运行期持续变化的），manifest.json 仅供人读/调试。
    """
    try:
        run_dir = _resolve_session_dir(_cwd_of(request), session_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="会话 ID 不合法") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc

    cwd = _cwd_of(request)
    state = _load_run_state(run_dir) or {}
    outputs_rel = state.get("outputs_dir")
    outputs_dir = (cwd / outputs_rel) if outputs_rel else (_outputs_root(cwd) / session_id)
    if not outputs_dir.is_dir():
        return {"session_id": session_id, "count": 0, "files": []}

    files = await asyncio.to_thread(_scan_outputs_for_manifest, outputs_dir)

    def _write_manifest() -> None:
        # manifest.json 落盘失败不阻断响应（artifacts 索引回填才是权威路径）
        try:
            atomic_write_text(
                outputs_dir / MANIFEST_NAME,
                json.dumps(
                    {"session_id": session_id, "generated_at": time.time(), "files": files},
                    ensure_ascii=False, indent=2,
                ),
            )
        except OSError:
            pass

    await asyncio.to_thread(_write_manifest)

    store = getattr(request.app.state, "platform_store", None)
    if store is not None:
        await asyncio.to_thread(store.replace_artifacts, session_id, files)
    return {"session_id": session_id, "count": len(files), "files": files}
@router.get("/chat/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    """取单个会话的全量归约历史（前端恢复聊天流用）。"""
    try:
        run_dir = _resolve_session_dir(_cwd_of(request), session_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="会话 ID 不合法") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    return {"id": session_id, "messages": _read_history(run_dir)}
async def _settle_active_turn(handle: _TurnHandle | None) -> None:
    """等一轮回合真正收尾（上限 DELETE_SETTLE_TIMEOUT_S）。

    R16 注册结构带真实 asyncio.Task，直接精确等待；超时（工具僵死未响应
    协作取消）则补一次协作信号加短硬取消兜底——即便仍未退出，迟到的写回
    也已被墓碑拦截，rmtree 不会被复活。
    """
    if handle is None or handle.task is None or handle.task.done():
        return
    _, pending = await asyncio.wait({handle.task}, timeout=DELETE_SETTLE_TIMEOUT_S)
    if pending:
        LOG.warning("删除会话：回合 %.0fs 未收尾，硬取消兜底",
                    DELETE_SETTLE_TIMEOUT_S)
        handle.cancel_event.set()
        handle.task.cancel()
        await asyncio.wait({handle.task}, timeout=2.0)
@router.delete("/chat/sessions/{session_id}")
async def delete_session(session_id: str, request: Request):
    """删除整个会话目录（含 run/events/history）。

    删除**运行中**的会话时先通知活跃连接：close(code=4002) 让前端立即
    离场，随后从 ``_ACTIVE`` 取真实回合句柄——置位 cancel_event 协作停止，
    并精确等到回合收尾（回复落盘/注册项摘除都发生在其 finally 里）再删。

    幽灵会话修复（A3）：rmtree 前**先落墓碑**——此后该会话的一切磁盘写回
    （history.json / run.json / events.jsonl）都在写回点被静默拦截并自删
    残留。即使回合收尾超过等待窗口，迟到的写回也不会把目录重建回幽灵
    会话；墓碑保留到进程结束或同名重建接管（见 _TOMBSTONES）。
    """
    try:
        run_dir = _resolve_session_dir(_cwd_of(request), session_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="会话 ID 不合法") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc

    # 墓碑先行：本语句与下方 rmtree 之间无 await（事件循环不会插入其他
    # 协程的写回），「先标后删」不给迟到写回任何复活窗口。
    _TOMBSTONES.add(session_id)

    live = _LIVE.get(session_id)
    if live is not None:
        try:
            await live.close(code=4002, reason="会话已被删除")
        except Exception:
            pass  # 尽力而为：socket 多半已断，关闭失败不影响删除主流程

    handle = _ACTIVE.get(session_id)
    if handle is not None:
        handle.cancel_event.set()
        await _settle_active_turn(handle)
    # 会话级运行时一并出清：预算账本与帧缓冲随目录一起消亡。
    _ACTIVE.pop(session_id, None)
    _SESSIONS.pop(session_id, None)

    shutil.rmtree(run_dir, ignore_errors=True)
    # R12 P2 双轨制：产物目录 1:1 归会话所有，显式删除时一并清掉
    shutil.rmtree(_outputs_root(_cwd_of(request)) / session_id, ignore_errors=True)
    # 迭代2：产物索引同步清除（防 /api/search artifacts scope 幽灵命中）
    _store = getattr(request.app.state, "platform_store", None)
    if _store is not None:
        try:
            await asyncio.to_thread(_store.drop_artifacts, session_id)
        except Exception:  # noqa: BLE001 —— 清索引失败不影响删除主流程
            pass
    return {"ok": True}
@router.patch("/chat/sessions/{session_id}")
async def rename_session(session_id: str, request: Request):
    """重命名会话：更新 run.json 的标题字段（query，列表摘要 title 的来源）。

    只改标题不动时间戳：SessionStore.save() 会把 updated_at 刷成当前时刻，
    而列表按 updated_at 倒序——改名不应把会话顶到列表最前。因此读出完整
    状态、仅替换 query 并原样保留 updated_at，经 atomic_write_text 原子写回
    （与 history.json 同一套断电安全口径）。run.json 损坏时按默认状态重建
    （与 SessionStore._load 的既有语义一致）。
    """
    try:  # body 容错与 create_session 同风格：空 body / 非 JSON 按 422 收场
        body = await request.json()
    except Exception:
        body = None
    raw_title = body.get("title") if isinstance(body, dict) else None
    title = str(raw_title or "").strip()[:80]  # 截断口径对齐 create_session
    if not title:
        raise HTTPException(status_code=422, detail="会话标题不能为空")
    try:
        run_dir = _resolve_session_dir(_cwd_of(request), session_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="会话 ID 不合法") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    # 幽灵会话拦截（A3，run_state 保存点）：已删除会话的改名写回会把目录
    # 重建回来——墓碑命中时按「会话不存在」收场（与 GET 同一 404 口径）。
    if session_id in _TOMBSTONES:
        raise HTTPException(status_code=404, detail="会话不存在")

    store = SessionStore(run_dir)
    state = store.state.to_dict()
    state["query"] = title  # 其余字段（含 created_at/updated_at）原样保留
    atomic_write_text(
        run_dir / SessionStore.RUN_FILE,
        json.dumps(state, indent=2, ensure_ascii=False),
    )
    store.log_event("session_rename", {"title": title})
    return {"ok": True, "id": session_id, "title": title}
_NETWORK_HINT = (
    "——无法连接模型端点。请检查：① Base URL 是否正确（设置页「测试连接」可验证）；"
    "② 本机网络能否直连该端点——境内服务请确认代理已关闭，"
    "境外服务需网络可达或设置 HTTPS_PROXY 环境变量后重启应用。"
)
ORPHAN_GRACE_S = max(30.0, float(os.getenv("RA_CHAT_ORPHAN_GRACE_SECONDS", "900")))
ORPHAN_HARD_CANCEL_S = 30.0
def _has_active_turn(sid: str) -> bool:
    """sid 是否已有**未结束**的活动回合。

    A+ 阶段 1 / C-4 的判定核心。独立成模块级函数有两个理由：一是
    ``_start_turn`` 里要复用主循环的同款判据，避免两处各写一份而漂移；
    二是它可被测——原先内联在协程里，只能靠构造竞态才能覆盖。
    """
    handle = _ACTIVE.get(sid)
    if handle is None:
        return False
    return not (handle.task is not None and handle.task.done())
def _register_connection(sid: str, websocket: Any, sink: Any) -> Any:
    """原子接管 sid 的连接登记，返回被替换掉的旧 socket（无则 None）。

    A+ 阶段 1 / C-3：本函数内**不得出现任何 await**。

    修复前是 `await previous.close()` 之后再写 `_LIVE`/`_SINKS`：那个挂起点
    让两条几乎同时进入的新连接互相覆盖——后写的把先写的踢出登记表，
    于是某条活跃连接拿不到帧，而另一条会收到不属于自己的回合输出。

    现在「读 previous + 同步占位」在无 await 段内一次完成，关闭旧连接交由
    调用方用后台任务处理（见 ``_close_quietly``）。
    """
    previous = _LIVE.get(sid)
    _LIVE[sid] = websocket
    _SINKS[sid] = sink
    return previous
async def _close_quietly(sock: Any, *, code: int, reason: str) -> None:
    """后台关闭一条 WebSocket，吞掉一切异常。

    A+ 阶段 1 / C-3 的配套：踢掉旧连接原本是 `await previous.close()`，
    那个挂起点正是 `_LIVE`/`_SINKS` 注册竞态的来源。改为后台任务后，
    关闭失败（连接已断、传输已关）不能影响新连接，故在此静默并记录。
    """
    try:
        await sock.close(code=code, reason=reason)
    except asyncio.CancelledError:
        raise
    except Exception:
        LOG.debug("关闭被替换的旧连接失败", exc_info=True)
async def _orphan_reap(sid: str, handle: _TurnHandle) -> None:
    """孤儿回合看门狗：最后一个观察者离开满 ORPHAN_GRACE_S 后收尸。

    先协作停止（内核在安全点响应 cancel_event 并正常落盘 partial 文本），
    短暂等待后仍未结束才硬取消。重连 attach 会 cancel 本任务——看门狗被
    取消是正常路径，在此吞掉 CancelledError 即可。
    """
    try:
        await asyncio.sleep(ORPHAN_GRACE_S)
        if _ACTIVE.get(sid) is not handle:
            return
        LOG.info("孤儿回合宽限到期，协作停止 sid=%s", sid)
        handle.cancel_event.set()
        await asyncio.wait({handle.task}, timeout=ORPHAN_HARD_CANCEL_S)
        if not handle.task.done():
            LOG.warning("回合未响应协作停止，硬取消兜底 sid=%s", sid)
            handle.task.cancel()
    except asyncio.CancelledError:
        pass  # 控制流：定时器自身被取消即正常退出路径
@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket, session: str | None = None):
    """通用 agentic 会话端点。

    server→client / client→server 全部帧型见 docs/protocol.md
    「会话协议 (/ws/chat)」一节。

    R16 耐久化：回合生命周期不再绑定连接——断开/刷新/Wi-Fi 抖动只让本
    连接退场（观察者 -1），运行中的回合继续跑到终态并把回复落盘；客户端
    重连后发 ``{"action":"attach","after":<seq>}`` 从环形缓冲回放错过的
    帧。回合的唯一终止途径：显式 stop、删除会话、或孤儿宽限到期
    （RA_CHAT_ORPHAN_GRACE_SECONDS，默认 900s）。这是对「断连即失败、
    回复永不落盘」缺陷（InvalidStateError 连锁）的结构性消除：发射路径
    不感知连接状态，不存在「发送失败→同步取任务结果」的窗口。
    """
    await websocket.accept()

    # A+ 阶段 1 / C-7：出站信箱**有界**，与任务侧（task_hub 的 maxsize=1000
    # + 满则丢最旧）保持同一背压口径。
    #
    # 修复前这里是无界队列：客户端读得慢（弱网、页面被系统节流、或干脆
    # 挂着一个不消费的 WebSocket）时，回合会持续往内存里堆帧——一个长回合
    # 的文本帧可达数万条，进程 RSS 无上限增长，而服务端没有任何信号表明
    # 「对端已经跟不上了」。
    #
    # 丢最旧而不是丢最新：帧流是**有序增量**，丢中间/最新会造成乱序或丢
    # 尾；丢最旧只是让该连接的直播流暂时落后，而完整序列仍在回合句柄的
    # 环形缓冲（FRAME_RING_CAP）里，重连 attach(after) 可以精确补回。
    outbox: asyncio.Queue = asyncio.Queue(maxsize=OUTBOX_MAXSIZE)
    #: 因信箱满而丢弃的帧数（仅本连接，用于日志；不回写帧对象）。
    outbox_dropped: list[int] = [0]
    sid = ""
    #: 本连接在 _SINKS 里的登记凭证（finally 按引用比对注销）。
    #:
    #: 必须**只绑定一次**并全程复用同一对象：``outbox.put_nowait`` 每次属性
    #: 访问都产生一个新的绑定方法对象，登记与注销各取一次的话 ``is`` 比对
    #: 恒为假。修复前这个变量从未被赋值（C-3 重构引入 ``_register_connection``
    #: 后漏接），导致 finally 的注销分支永远不成立，``_SINKS`` 按会话数无界
    #: 增长——断连后条目仍指向死信箱，回合帧持续投递进永不被消费的队列。
    sink_fn: Any = outbox.put_nowait
    #: 本连接正在观察的回合句柄：finally 时逐个释放名额——归零且回合仍在
    #: 跑则在那里武装孤儿看门狗。同一连接至多观察一个活动回合。
    watching: list[_TurnHandle] = []

    async def _pump() -> None:
        """出站泵：全连接唯一真正 send_json 的地方。

        单消费者天然串行化所有帧（取代旧 send_lock）；发送失败即退出——
        余帧已入环形缓冲的照旧可 attach 回放，本连接此后不再出帧。
        """
        while True:
            frame = await outbox.get()
            try:
                await websocket.send_json(frame)
            except Exception:
                break

    pump_task = asyncio.get_running_loop().create_task(_pump())

    def _post(frame: dict) -> None:
        """同步入箱（不 await）。事件循环协作式调度下，「快照→过滤→补发」
        因此可以写成无 await 的原子段——回合任务的发射不可能插进回放中间，
        回放帧与直播帧在同一 FIFO 里严格保序、不重不漏。

        满则丢最旧（见 ``bounded_put``）；落后量经日志暴露，不塞进每一帧——
        入队对象可能与环形缓冲共享引用，就地改写会污染回放源。
        """
        if bounded_put(outbox, frame):
            outbox_dropped[0] += 1
            if outbox_dropped[0] == 1 or outbox_dropped[0] % 500 == 0:
                LOG.warning(
                    "出站信箱已满，丢弃最旧帧 sid=%s 累计丢弃=%d"
                    "（对端消费过慢，完整序列仍可经 attach 回放补回）",
                    sid, outbox_dropped[0],
                )

    async def _drain() -> None:
        """等信箱清空再返回（close 前确保错误帧真的发出去）。

        仅用于早退路径（信箱至多一两帧）：每次 sleep(0) 让泵推进一步。
        迭代上限是防御——泵若意外退出也不至于在这里挂死。"""
        for _ in range(200):
            if outbox.empty():
                return
            await asyncio.sleep(0)

    async def _send(frame: dict) -> None:
        """发一帧：入箱由泵串行送达；断连后泵退场、帧自然弃发（静默）。"""
        _post(frame)

    async def _emit(handle: _TurnHandle, frame: dict) -> None:
        """回合帧统一出口：登记 seq 入环形缓冲，再路由到当前活跃连接。

        路由按 sid 现查 _SINKS——不是闭包绑死的发起连接（那是「attach 只
        回放快照」缺陷的根源）。next_seq + 查表 + 入箱全程无 await，与
        _handle_attach 的同步回放段互斥，跨源帧序由此保证。无连接时静默：
        帧留在环形缓冲等 attach 回放。
        """
        stamped = handle.next_seq(frame)
        sink = _SINKS.get(sid)
        if sink is not None:
            sink(stamped)

    def _release(handle: _TurnHandle) -> None:
        """归还一个观察者名额；归零且回合仍在跑则武装孤儿看门狗。"""
        if handle not in watching:
            return
        watching.remove(handle)
        handle.observers = max(0, handle.observers - 1)
        if (
            handle.observers == 0
            and sid in _ACTIVE
            and _ACTIVE.get(sid) is handle
            and handle.orphan_task is None
            and not handle.task.done()
        ):
            handle.orphan_task = asyncio.get_running_loop().create_task(
                _orphan_reap(sid, handle)
            )

    def _observe(handle: _TurnHandle) -> None:
        """登记观察者：有人看着了，撤销孤儿看门狗。"""
        if handle.orphan_task is not None:
            handle.orphan_task.cancel()
            handle.orphan_task = None
        handle.observers += 1
        if handle not in watching:
            watching.append(handle)

    try:
        cwd = _cwd_of(websocket)
        root = _sessions_root(cwd)

        # ---- 定位或新建会话目录 ------------------------------------------
        if session:
            candidate = session.strip()
            if not _valid_session_id(candidate):
                await _send({"type": "error", "message": "会话 ID 不合法"})
                await _drain()
                await websocket.close()
                return
            # 目录不存在时按同名自动重建（幂等进入：删除后的会话可无缝再开）
            run_dir = root / candidate
            run_dir.mkdir(parents=True, exist_ok=True)
            try:
                safe_resolve(run_dir, root)
            except ValueError:  # 符号链接等越界：与 _valid_session_id 双保险
                await _send({"type": "error", "message": "会话 ID 不合法"})
                await _drain()
                await websocket.close()
                return
            # 显式以旧名字重连 = 新化身接管（与 _new_session_dir 同一口径）：
            # 解除墓碑，否则本会话的一切落盘都会被拦截成幽灵。
            _TOMBSTONES.discard(candidate)
        else:
            run_dir = _new_session_dir(root, "")
        sid = run_dir.name

        if (run_dir / SessionStore.RUN_FILE).is_file():
            store = SessionStore(run_dir)
            store.state.mode = "chat"  # 兼容：老目录补齐 mode 标记
        else:
            store = SessionStore.create(
                run_dir,
                query="",
                model=resolve_model(None),
                mode="chat",
            )
        store.save()
        store.log_event("session_open", {"via": "ws"})

        # ---- R12 P2 双轨制：连接即建本会话产物目录 -------------------------
        # 不能推迟到首回合：frozen_exec 对不存在的 CWD 硬失败。旧会话重连
        # （run.json 缺 outputs_dir 的 legacy 目录）在此惰性补建并回填落盘。
        outputs_abs = _outputs_root(cwd) / sid
        try:
            outputs_abs.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            LOG.warning("产物目录创建失败 sid=%s：%s", sid, exc)
            await _send({"type": "error",
                         "message": f"无法创建产物目录 {outputs_abs}：{exc}"})
            await _drain()
            await websocket.close()
            return
        if store.state.outputs_dir != f"outputs/{sid}":
            store.state.outputs_dir = f"outputs/{sid}"  # 相对 POSIX 口径
            store.save()

        # ---- 并发连接：踢掉同会话旧 socket --------------------------------
        #
        # A+ 阶段 1 / C-3：**先同步占位，再异步关旧连接**。
        #
        # 修复前 `await previous.close(...)` 是挂起点：两条新连接 C1、C2 几乎
        # 同时进来时，C1 在 await 处让出 → C2 读到的 previous 仍是 A_old，
        # 关掉它并把自己写进 _LIVE/_SINKS → C1 恢复后**覆盖** C2。
        # 结果是 C2 明明活着却不在 _SINKS 里：C2 的回合帧被投递给 C1 的信箱
        # ——一个标签页看到另一个会话的输出，而自己这边永远空白。
        #
        # 修复要点是让「读 previous → 写 _LIVE/_SINKS」落在**无 await 的
        # 原子段**内，把真正需要 await 的 close 挪出去用后台任务做。
        # 传 sink_fn（本连接一次性绑定的方法对象）而不是现场取
        # outbox.put_nowait——后者是新对象，finally 的 `is` 比对会失配。
        previous = _register_connection(sid, websocket, sink_fn)
        if previous is not None and previous is not websocket:
            # 被踢连接在自己的 finally 里释放观察者名额——若它正观察着活动
            # 回合且无新连接接替，孤儿看门狗会在那里武装。
            asyncio.get_running_loop().create_task(
                _close_quietly(previous, code=4001, reason="replaced by newer connection")
            )

        # ---- 会话级运行时：预算跨重连持续累计 ------------------------------
        rt = _SESSIONS.setdefault(sid, {})
        budget = rt.get("budget")
        if budget is None:
            # 连接期确定初始计价模型，每轮开始前跟随实际配置重新计价——
            # 不能用 lifespan 的模型快照钉死会话。
            budget = BudgetGuard(model=resolve_model(None))  # limits 自 RA_MAX_* 继承
            rt["budget"] = budget

        # 双轨制注入：sandbox 围栏恒为工作区根；相对写入与执行默认 CWD 归巢
        # 产物目录（savefig 相对保存自动落家）；读共享数据靠契约绝对路径口径。
        #
        # A+ 阶段 2 / F-2：注入 PlatformStore 与 sid，开启产物索引**推模式**——
        # 工具写成功即回填 artifacts 表，该表由此成为唯一权威源。此前的拉模式
        # 只在有人调用 manifest 端点时才回填，没人查就不记。
        # CLI / 单代理路径不注入，行为不变。
        _platform_store = getattr(websocket.app.state, "platform_store", None)
        tools = ToolRegistry(
            work_dir=str(cwd),
            write_anchor=str(outputs_abs),
            exec_cwd=str(outputs_abs),
            artifact_store=_platform_store,
            artifact_session=sid,
        )

        # A+ 阶段 5 / G-1：跨会话记忆。工具三件套经声明式扩展注册（存/取/忘），
        # 既有记忆摘要在**连接建立时**注入系统提示（每回合重复构建
        # system_instructions 时的读取成本 = 一次 JSON 读，可忽略；回合中
        # 新存的记忆从下一轮提示可见——模型也可 recall_memory 即时取）。
        _memory_store = build_memory_store(cwd)
        for _ext in build_memory_extensions(cwd, store=_memory_store):
            tools.register_extension(_ext)
        system_instructions = _chat_system_instructions(cwd, outputs_abs)
        memory_section = memory_prompt_section(_memory_store)
        if memory_section:
            system_instructions += memory_section

        card_seq = itertools.count(1)  # 卡片 ID 连接内唯一（跨轮不重置：
        # 前端 cards 映射按 id 合并；回合私有的是 pending_cards FIFO 配对表）

        async def _on_text(handle: _TurnHandle, delta: str) -> None:
            # 流式路径：run_agent 把该回调作为 on_chunk 传给 LLM client，
            # 因此这里是逐段增量而非整轮文本。增量同步入账 partial_text：
            # 异常/硬取消路径的兜底文本来源（agent_result 拿不到时仍有它）。
            if delta:
                handle.partial_text += delta
                await _emit(handle, {"type": "text", "delta": delta})

        async def _on_thought(handle: _TurnHandle, delta: str) -> None:
            # R17 思考链（阶段4）：思考增量走 channel="thought" 的 text 帧——
            # 不加新帧型（旧客户端忽略 channel 字段，语义等同正文前行为：
            # 此前思考根本不显示）；绝不入账 partial_text（正文权威不含思考）。
            if delta:
                await _emit(
                    handle, {"type": "text", "delta": delta, "channel": "thought"},
                )

        async def _on_plan_text(handle: _TurnHandle, delta: str) -> None:
            # R17 思考链分级（阶段3）：planner 直播打 channel="plan" 标记，
            # 前端据此折叠进 L1 过程区而非正文气泡；文本仍入账 partial_text
            #（plan_proposal 的兜底来源，与 _on_text 口径一致）。
            if delta:
                handle.partial_text += delta
                await _emit(
                    handle, {"type": "text", "delta": delta, "channel": "plan"},
                )

        async def _start_turn(
            text: str,
            attachments: list[dict],
            plan_query: str | None = None,
        ) -> None:
            """装配并 spawn 一轮对话；立即返回，主循环继续收 steer/审批/stop。

            plan_query（方案 1）：非 None 时本回合先走 Plan 确认门——只读
            planner 回合产出计划（text 帧直播给用户）→ plan_proposal 帧 →
            等客户端 plan_decision；批准后才执行原请求（模型可见提示词里
            附上已确认的计划）。"""
            turn_t0 = time.monotonic()

            # A+ 阶段 1 / C-4：入口处二次确认没有活动回合。
            #
            # 主循环在调用本函数前已查过一次，但那次检查与这里的
            # `_ACTIVE[sid] = handle` 之间存在间隙；一旦 C-3 的竞态让两条
            # 连接并存，两个回合就会同时对 history.json 做
            # read-modify-write 而丢更新。此处是**第二道防线**：本函数从
            # 入口到写入 _ACTIVE 之间没有 await，所以这个检查是原子的。
            # 正常路径永远不会触发（调用方已把在途消息转成 steer）。
            if _has_active_turn(sid):
                LOG.warning(
                    "拒绝并发回合：sid=%s 已有活动回合（调用方应先走 steer 路径）", sid
                )
                return

            handle = _TurnHandle(cancel_event=asyncio.Event(), budget=budget)
            # seq 会话内单调续接：此刻 rt["last"] 仍是上一回合句柄（本回合
            # 的赋值在 spawn 之后），新游标从它续跑，保证 attach(after) 的
            # 过滤语义跨回合成立。
            prev_handle = rt.get("last")
            if prev_handle is not None:
                handle.seq = prev_handle.seq
            # 队列以句柄字段为权威（数据类自带实例）：_dispatch 的回执/steer、
            # 任务表注册项与内核消费的必须是同一对象——各建各的会让回执永远
            # 等不到人收（审批侧表现为 120s 超时假死）。
            approvals = handle.approvals
            steers = handle.steers
            ask_state = handle.ask_state

            def _push_approval(req: ToolApprovalRequest) -> None:
                ask_id = req.request_id or uuid.uuid4().hex
                ask_state["current"] = ask_id
                # 同步回调里发帧只能借道任务；审批帧稀疏，顺序抖动可接受，
                # seq 已在缓冲中保序、回放侧不受影响。
                asyncio.get_running_loop().create_task(
                    _emit(
                        handle,
                        {
                            "type": "approval_request",
                            "id": ask_id,
                            "tool": req.tool_name,
                            "summary": req.summary(),
                            "agent_id": req.agent_id,
                            "role": req.agent_role,
                        },
                    )
                )

            handle.approver = QueueApprover(
                approvals, timeout=120.0, on_request=_push_approval
            )

            pending_cards: deque[str] = deque()  # 工具顺序执行：FIFO 配对结束回调

            async def _on_tool_start(tool: str, args: dict) -> None:
                cid = f"c{next(card_seq)}"
                pending_cards.append(cid)
                await _emit(
                    handle,
                    {
                        "type": "tool_card",
                        "id": cid,
                        "tool": tool,
                        "arguments": _jsonable_arguments(args),
                        "status": "running",
                        "result_preview": "",
                        "files": [],
                    },
                )

            async def _on_tool_use(tool: str, args: dict, result: object) -> None:
                text_out = result if isinstance(result, str) else str(result)
                # 被拒/出错的调用不会触发 on_tool_start，这里兜底补发终态卡
                cid = pending_cards.popleft() if pending_cards else f"c{next(card_seq)}"
                status = "error" if text_out.startswith(("Error", "[DENIED")) else "done"
                await _emit(
                    handle,
                    {
                        "type": "tool_card",
                        "id": cid,
                        "tool": tool,
                        "arguments": _jsonable_arguments(args),
                        "status": status,
                        "result_preview": text_out[:PREVIEW_LIMIT],
                        "files": extract_artifact_paths(tool, args, text_out),
                    },
                )

            # ---- 历史：用户消息先行落盘（崩溃可恢复） -------------------------
            messages = _read_history(run_dir)
            user_entry: dict[str, Any] = {"role": "user", "content": text}
            if attachments:
                user_entry["attachments"] = attachments
            messages.append(user_entry)
            _write_history(run_dir, messages)
            store.save()
            store.log_event("turn_start", {"chars": len(text)})
            # 方案 4：/model 会话级覆盖优先；/role、/skill 攒在 pending_context
            # 里，只对本回合生效（取用即清，不跨回合残留）。
            model_now = rt.get("model_override") or resolve_model(None)
            system_now = system_instructions
            pending_ctx = rt.pop("pending_context", [])
            if pending_ctx:
                lines = "\n".join(
                    f"- {'角色设定' if kind == 'role' else '技能注入'}：{value}"
                    for kind, value in pending_ctx
                )
                system_now += f"\n\n## 本回合 slash 命令追加上下文\n{lines}"
            LOG.info("回合开始 sid=%s 字数=%d 模型=%s%s",
                     sid, len(text), model_now,
                     " [plan]" if plan_query is not None else "")
            history_prefix = [_content_for_llm(m) for m in messages[:-1]]
            # 多模态（G-3）：本回合的图片附件作为 image 部件并入本轮上下文。
            # 内核 run_agent 只接收字符串 prompt（user 消息由它自行追加），
            # 因此图片以独立 user 条目挂在 initial_messages 尾部，与紧随的
            # prompt 文本消息在协议适配层合并为一条多部件 user 消息。
            current_images = _image_parts_from_entry(user_entry)
            if current_images:
                history_prefix.append({"role": "user", "content": current_images})

            async def _invoke(user_prompt: str):
                # 每轮实时构建客户端：设置页保存即刻生效；历史由包装层前置
                # 进本轮首个请求（_HistoryClient），内核仍从单条 user 起步。
                llm_client = _HistoryClient(build_llm_client(model=model_now))
                llm_client.set_prefix([])
                # G-6 执行链路 tracing：RA_TRACE_DIR 设置时每次 run 写
                # trace-<ts>.jsonl；未设置返回 None、不注册任何 handler。
                run_hooks = HookBus()
                maybe_attach_tracing(run_hooks)
                try:
                    return await run_agent(
                        prompt=user_prompt,
                        system_prompt=system_now,
                        llm_client=llm_client,
                        tools=tools,
                        config=RunConfig(
                            # 会话语义：一条用户消息一轮回复，自然停即停。
                            auto_continue=False,
                            budget=budget,
                            cancel_event=handle.cancel_event,
                            approver=handle.approver,
                            session_log=store,  # events.jsonl 审计镜像
                            initial_messages=history_prefix,
                            hooks=run_hooks,
                        ),
                        on_text=lambda delta: _on_text(handle, delta),
                        on_thought=lambda delta: _on_thought(handle, delta),
                        on_tool_start=_on_tool_start,
                        on_tool_use=_on_tool_use,
                        steer_queue=steers,
                    )
                finally:
                    try:
                        await llm_client.close()
                    except Exception:
                        pass  # 尽力而为：连接收尾失败不掩盖本轮真实结果

            async def _wait_plan_decision(active: _TurnHandle) -> str:
                """等 plan_decision / stop / 超时，返回 approve|deny|timeout|cancel。"""
                recv = asyncio.ensure_future(active.plans.get())
                stop_wait = asyncio.ensure_future(active.cancel_event.wait())
                done, pending_set = await asyncio.wait(
                    {recv, stop_wait},
                    timeout=PLAN_DECISION_TIMEOUT_S,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending_set:
                    t.cancel()
                if recv in done:
                    return str(recv.result())
                return "cancel" if stop_wait in done else "timeout"

            async def _run_plan_gate(query: str) -> tuple[bool, str]:
                """方案 1：只读 planner 回合 → plan_proposal → 等待裁决。

                返回 (是否批准, 计划文本)。计划经 on_text 已实时直播给用户
                （并累积进 partial_text）；无论批准与否，计划都作为 assistant
                条目落盘——它是本轮 /plan 请求的真实回复。
                """
                plan_text = ""
                llm_client = _HistoryClient(build_llm_client(model=model_now))
                # G-6：planner 回合同样按 env 开关挂 tracing（独立 run 独立文件）
                plan_hooks = HookBus()
                maybe_attach_tracing(plan_hooks)
                try:
                    result = await run_agent(
                        prompt=query,
                        system_prompt=_planner_instructions(system_now),
                        llm_client=llm_client,
                        tools=_PlannerTools(),  # 只读规划：无工具面
                        config=RunConfig(
                            auto_continue=False,
                            budget=budget,
                            cancel_event=handle.cancel_event,
                            session_log=store,
                            initial_messages=history_prefix,
                            hooks=plan_hooks,
                        ),
                        on_text=lambda delta: _on_plan_text(handle, delta),
                    )
                    plan_text = (
                        (getattr(result, "text_output", "") or "")
                        or handle.partial_text
                    ).strip()
                finally:
                    try:
                        await llm_client.close()
                    except Exception:
                        pass  # 尽力而为：连接收尾失败不掩盖本轮真实结果
                plan_id = uuid.uuid4().hex
                handle.ask_state["plan"] = plan_id
                await _emit(handle, {
                    "type": "plan_proposal",
                    "id": plan_id,
                    "plan": plan_text,
                })
                decision = await _wait_plan_decision(handle)
                handle.ask_state["plan"] = ""
                store.log_event("plan_decision", {
                    "decision": decision,
                    "chars": len(plan_text),
                })
                if decision != "approve":
                    # 未批准：给流里补一句明确的收场说明，随计划一并入史
                    note = "\n\n——计划未获批准（或确认超时），本轮不执行。"
                    handle.partial_text += note
                    await _emit(handle, {"type": "text", "delta": note})
                    plan_text = (plan_text + note).strip()
                # 计划即刻落盘（批准与否都一样）：它是本轮 /plan 请求的真实
                # 回复；即便执行阶段崩溃，计划也不丢（全路径持久化口径）。
                if plan_text:
                    messages.append({"role": "assistant", "content": plan_text})
                    _write_history(run_dir, messages)
                return decision == "approve", plan_text

            async def _feeder(agent_task):
                # 运行期每 ~1s 推一帧 usage 快照，结束至少一帧。本循环从不
                # 中途 break——usage_ticks 的生成器只在自然耗尽（任务已完成）
                # 时才走 finally，其 task.cancel() 兜底不可能误杀运行中回合。
                async for frame in usage_ticks(agent_task, budget):
                    await _emit(handle, frame)

            async def _turn_main() -> None:
                agent_result: Any = None
                failure: BaseException | None = None
                plan_text = ""
                plan_denied = False
                try:
                    if plan_query is not None:
                        approved, plan_text = await _run_plan_gate(plan_query)
                        if not approved:
                            plan_denied = True
                        else:
                            # 计划已单独作为 assistant 条目落盘（见下），
                            # 重置流式累积——执行阶段的 partial 只算执行文本。
                            handle.partial_text = ""
                    if not plan_denied:
                        model_prompt = text
                        if plan_query is not None and plan_text:
                            model_prompt = (
                                f"{text}\n\n[已确认的执行计划]\n{plan_text}\n\n"
                                "请严格按上述计划执行，完成后汇报结果与产物路径。"
                            )
                        agent_task = asyncio.ensure_future(_invoke(model_prompt))
                        handle.feeder = asyncio.ensure_future(_feeder(agent_task))
                        agent_result = await agent_task
                except asyncio.CancelledError:
                    # 硬取消（服务关闭 / 删除兜底）：已流出文本回调层有账
                    failure = asyncio.CancelledError()
                except Exception as exc:
                    failure = exc
                finally:
                    # 收尾帧保证：agent 落定后 usage_ticks 生成器会被已满足的
                    # wait 立即唤醒、发出最后一帧再自然返回——给泵最多 0.5s
                    # 发完；超时（理论上仅 socket 死锁）才取消兜底。不能盲目
                    # cancel，否则「结束至少一帧 usage」语义丢失。
                    if handle.feeder is not None and not handle.feeder.done():
                        done, _ = await asyncio.wait({handle.feeder}, timeout=0.5)
                        if not done:
                            handle.feeder.cancel()
                            try:
                                await handle.feeder
                            except BaseException:
                                pass  # 尽力而为清理：等待已取消的 feeder 收尾，异常不再上抛
                    handle.feeder = None

                # ---- 全路径持久化：用户消息之后必有 assistant 条目 -------------
                # Plan 门拒绝路径：计划条目已在 _run_plan_gate 落盘，本轮到此
                # 收场（cancelled），不再追加执行回复。
                if plan_denied:
                    if failure is None:
                        failure = asyncio.CancelledError()
                    reply, stop_reason = "", "cancelled"
                elif failure is None:
                    reply = ((getattr(agent_result, "text_output", "") or "")
                             or handle.partial_text).strip()
                    stop_reason = str(getattr(agent_result, "stop_reason", "") or "")
                elif isinstance(failure, asyncio.CancelledError):
                    reply, stop_reason = handle.partial_text.strip(), "cancelled"
                else:
                    reply, stop_reason = handle.partial_text.strip(), "error"
                cancelled = (
                    stop_reason == "cancelled"
                    or isinstance(failure, asyncio.CancelledError)
                )
                errored = (
                    (failure is not None and not isinstance(failure, asyncio.CancelledError))
                    or stop_reason == "error"
                )
                status = "cancelled" if cancelled else ("failed" if errored else "complete")
                # partial 标记：文本是残缺回答（被打断/失败），前端可提示续问
                partial_flag = bool(reply) and (cancelled or errored)

                if reply:
                    done_entry: dict[str, Any] = {"role": "assistant", "content": reply}
                    if partial_flag:
                        done_entry["partial"] = True
                    messages.append(done_entry)
                    _write_history(run_dir, messages)
                LOG.info("回合结束 sid=%s 状态=%s 用时=%.1fs 字数=%d",
                         sid, status, time.monotonic() - turn_t0, len(reply))
                store.finish(status, budget.snapshot())

                if errored and failure is not None:
                    message = str(failure) + (
                        _NETWORK_HINT if _is_network_error(failure) else ""
                    )
                    LOG.warning("回合失败 sid=%s 用时=%.1fs：%s",
                                sid, time.monotonic() - turn_t0, str(failure)[:300])
                    # R17 思考链分级：L0 给人性化摘要，traceback 作可选字段
                    # 供「调试」档展示堆栈（协议新增可选字段，旧客户端忽略）。
                    error_frame: dict[str, Any] = {"type": "error", "message": message}
                    error_frame["traceback"] = "".join(
                        traceback.format_exception(failure)
                    )[-4000:]
                    await _emit(handle, error_frame)
                await _emit(
                    handle,
                    {
                        "type": "result",
                        "stop_reason": stop_reason,
                        "turns": int(getattr(agent_result, "turns", 0) or 0),
                    },
                )
                handle.status = status

            def _cleanup_turn() -> None:
                """回合收尾清理：活动表/任务注册项。幂等，硬取消路径同样覆盖。"""
                if _ACTIVE.get(sid) is handle:
                    _ACTIVE.pop(sid, None)
                tasks_reg = getattr(websocket.app.state, "active_tasks", None)
                if isinstance(tasks_reg, dict):
                    reg = tasks_reg.get(f"chat:{sid}")
                    if isinstance(reg, dict) and reg.get("task") is handle.task:
                        tasks_reg.pop(f"chat:{sid}", None)

            async def _turn_main_wrapped() -> None:
                try:
                    await _turn_main()
                finally:
                    _cleanup_turn()

            handle.task = asyncio.ensure_future(_turn_main_wrapped())
            _ACTIVE[sid] = handle
            rt["last"] = handle
            tasks_reg = getattr(websocket.app.state, "active_tasks", None)
            if isinstance(tasks_reg, dict):  # 注册到任务表：REST stop 可达 +
                # 删除端点的精确等待分支自此有真实 task 对象可等。
                tasks_reg[f"chat:{sid}"] = {
                    "status": "running",
                    "query": text[:100],
                    "cancel_event": handle.cancel_event,
                    "approvals": approvals,
                    "steers": steers,
                    "task": handle.task,
                }
            _observe(handle)

        async def _handle_attach(msg: dict) -> None:
            """回放协议入口：把错过的帧按 seq 补发给（重）连接的客户端。

            有活动回合→接管观察（撤销孤儿看门狗）；只有刚结束的回合→照常
            回放（客户端借此无损恢复上一回合全过程）；都没有→replay_empty，
            客户端回落 REST 历史渲染。
            """
            try:
                after = int(msg.get("after") or 0)
            except (TypeError, ValueError):
                after = 0
            after = max(0, after)
            target = _ACTIVE.get(sid) or (_SESSIONS.get(sid) or {}).get("last")
            if target is None:
                await _send({"type": "replay_empty"})
                return
            # A+ 阶段 1 / C-2：重复 attach **只打日志就放行**是错的。
            #
            # `_observe` 无条件 `observers += 1`，但 `watching.append` 是有
            # 条件的；而 `_release` 以 `watching` 为准（不在其中直接 return）。
            # 于是同一连接 attach 两次 → observers=2 而 watching 只有 1 项
            # → 断连只减 1 → observers 停在 1 → `observers == 0` 永不成立
            # → **孤儿看门狗永不武装**，无人观察的回合会一直跑到预算耗尽。
            #
            # 断连重连在网络抖动场景下很常见，这个洞是可达的。
            already = target in watching
            if already:
                # 仍回放一次（幂等：按 after 游标续播），但不再占用观察者名额。
                LOG.debug("重复 attach 同一回合 sid=%s after=%d —— 不再累加观察者", sid, after)
            else:
                _observe(target)
            # 下面整段无 await（_post 同步入箱）：快照、过滤、begin/帧/end
            # 的入箱顺序对回合任务的并发发射是原子的——要么 emit 整段先跑
            # （其 seq 进了快照、由回放补发），要么整段后跑（由直播路由送
            # 达）。绝不出现「半段回放 + 半段直播」交错导致的乱序/重复。
            _post({
                "type": "replay_begin",
                "last_seq": target.seq,
                "status": target.status,
            })
            for frame in list(target.frames):  # 快照迭代：边回放边新增也安全
                if frame.get("seq", 0) > after:
                    _post(frame)
            _post({
                "type": "replay_end",
                "status": target.status,
                "last_seq": target.seq,
            })
            if already:
                LOG.debug("重复 attach 同一回合 sid=%s after=%d", sid, after)

        async def _handle_command(name: str, rest: str, raw: str) -> None:
            """方案 4：slash 命令服务端分派（不进历史、不占回合）。

            /plan 不在此处理——它要在主循环 user 分支里启动带确认门的回合
            （用户消息需要先落盘）。命令回执用 ``command`` 帧（raw 原文 +
            message 确认文案），前端渲染成 用户气泡 + 助手说明。
            """
            if name == "help":
                await _send({"type": "command", "command": "help",
                             "message": COMMAND_HELP_TEXT, "raw": raw})
            elif name == "budget":
                error = _apply_budget_override(budget, rest)
                if error:
                    await _send({"type": "error", "message": error})
                else:
                    await _send({"type": "command", "command": "budget",
                                 "message": _budget_limits_summary(budget),
                                 "raw": raw})
            elif name == "model":
                parts = rest.split()
                if not parts:
                    await _send({"type": "error", "message": "用法：/model <模型名>"})
                else:
                    value = parts[0]
                    rt["model_override"] = value
                    budget.set_model(value)  # 计价跟随，成本快照不失真
                    await _send({"type": "command", "command": "model",
                                 "message": f"本会话后续回合将使用模型 {value}。",
                                 "raw": raw})
            elif name in ("role", "skill"):
                parts = rest.split()
                if not parts:
                    await _send({"type": "error",
                                 "message": f"用法：/{name} <名称>（下一回合生效）"})
                else:
                    rt.setdefault("pending_context", []).append((name, parts[0]))
                    await _send({"type": "command", "command": name,
                                 "message": f"/{name} {parts[0]} 将在下一回合注入系统上下文。",
                                 "raw": raw})
            else:
                await _send({"type": "error",
                             "message": f"未知命令: /{name}（输入 /help 查看可用命令）"})

        async def _dispatch(msg: dict) -> None:
            """处理非 user 动作：审批回执 / Plan 裁决 / steer / stop / attach / 命令。"""
            action = msg.get("action")
            handle = _ACTIVE.get(sid)
            if action == "approval":
                if handle is None:
                    return  # 无活动回合：迟到回执无处可去，忽略
                ask_id = str(msg.get("id") or "")
                if ask_id and ask_id == handle.ask_state["current"]:
                    handle.ask_state["current"] = ""
                    # QueueApprover 按字符串真值判定："true" 在 _YES 集内
                    handle.approvals.put_nowait(str(bool(msg.get("approved"))).lower())
                # 迟到 / 未知 id 的回执直接忽略：避免残留答案自动应答下一次问询
            elif action == "steer":
                message = str(msg.get("message") or "").strip()
                if not message:
                    await _send({"type": "error", "message": "steer 内容不能为空"})
                elif len(message) > MAX_STEER_LENGTH:
                    await _send(
                        {"type": "error",
                         "message": f"steer 过长（最大 {MAX_STEER_LENGTH} 字符）"}
                    )
                elif handle is None:
                    await _send({"type": "error", "message": "当前没有运行中的回合"})
                else:
                    handle.steers.put_nowait(message)
            elif action == "stop":
                if handle is not None:
                    handle.cancel_event.set()
            elif action == "plan_decision":
                # 方案 1：Plan 门裁决。id 必须匹配当前待决计划——迟到/未知
                # id 的回执直接忽略（与工具审批同口径，防残留答案串道）。
                if handle is not None:
                    pid = str(msg.get("id") or "")
                    if pid and pid == handle.ask_state.get("plan", ""):
                        handle.ask_state["plan"] = ""
                        handle.plans.put_nowait(
                            "approve" if msg.get("approved") else "deny"
                        )
            elif action == "command":
                # 方案 4：空闲期命令。运行中不会走到这里——运行期的 user/
                # command 都在主循环按 steer 转交。
                raw = str(msg.get("text") or "").strip()
                if not raw.startswith("/"):
                    await _send({"type": "error", "message": "命令必须以 / 开头"})
                else:
                    name, rest = _split_slash(raw)
                    await _handle_command(name, rest, raw)
            elif action == "attach":
                await _handle_attach(msg)
            else:
                await _send({"type": "error", "message": f"未知 action: {action}"})

        LOG.info("会话连接建立 sid=%s outputs=%s", sid, store.state.outputs_dir)
        # connected 帧是前端 dock 的权威源：REST 列表在工作区切换后会把
        # dock 错接到另一工作区的同名目录，这里以本连接的 cwd 为准。
        await _send({
            "type": "connected",
            "session_id": sid,
            "outputs_dir": store.state.outputs_dir,
        })

        # ---- 主循环：空闲期直接接收；user 触发回合（spawn 后立即返回） -----
        while True:
            msg = await websocket.receive_json()
            if msg.get("action") == "user":
                text = str(msg.get("text") or "").strip()
                if not text:
                    await _send({"type": "error", "message": "消息不能为空"})
                elif len(text) > MAX_USER_LENGTH:
                    await _send(
                        {
                            "type": "error",
                            "message": f"消息过长（最大 {MAX_USER_LENGTH} 字符）",
                        }
                    )
                else:
                    active = _ACTIVE.get(sid)
                    # 收尾窗口守卫：result 帧在 _turn_main 的 finally（含最长
                    # 0.5s 的 feeder 等待）之前就到了客户端，客户端立刻追问
                    # 时 _ACTIVE 可能还挂着已结束的旧句柄——此刻转 steer 等于
                    # 把话塞进无人消费的队列（幽灵消息，界面永久沉默）。
                    # 任务对象已 done 即视为空闲，放行走新回合。
                    active_live = active is not None and not (
                        active.task is not None and active.task.done()
                    )
                    if active_live:
                        # 运行中收到新消息：按 steer 转交（原行为保留——
                        # 前端输入框在运行期本就是 steer 通道）。
                        active.steers.put_nowait(text[:MAX_STEER_LENGTH])
                        continue
                    atts_meta, att_err = _prepare_attachments(cwd, sid, msg.get("attachments"))
                    if att_err:
                        await _send({"type": "error", "message": att_err})
                        continue
                    # 方案 4：空闲期收到 slash 命令——/plan 启动带确认门的回合
                    #（用户消息照常落盘），其余命令就地分派（不占回合）。
                    if text.startswith("/"):
                        name, rest = _split_slash(text)
                        if name == "plan":
                            if not rest:
                                await _send({
                                    "type": "error",
                                    "message": ("用法：/plan <请求内容>——"
                                                "助手先给出计划，确认后再执行"),
                                })
                            else:
                                await _start_turn(text, atts_meta, plan_query=rest)
                        else:
                            await _handle_command(name, rest, text)
                        continue
                    await _start_turn(text, atts_meta)
            else:
                await _dispatch(msg)

    except WebSocketDisconnect:
        # R16：断连不再是取消信号——回合继续跑；观察者名额在 finally 归还。
        LOG.info("会话连接断开 sid=%s", sid)
    except Exception as exc:
        LOG.warning("会话连接异常 sid=%s：%s", sid, str(exc)[:300])
        try:  # 直发绕过泵：此刻 socket 大概率已坏，尽力而为、不掩盖原异常
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        for h in list(watching):
            _release(h)
        if sid and _LIVE.get(sid) is websocket:
            _LIVE.pop(sid, None)
        if sink_fn is not None and _SINKS.get(sid) is sink_fn:
            _SINKS.pop(sid, None)
        pump_task.cancel()
        try:
            await pump_task
        except asyncio.CancelledError:
            pass  # 控制流：泵任务按计划被取消，属正常收尾
