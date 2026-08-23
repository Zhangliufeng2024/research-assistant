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
import re
import shutil
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from ..agent import RunConfig, run_agent
from ..api import usage_ticks
from ..config import build_llm_client, resolve_model
from ..core import execution_contract_addendum, load_system_instructions, safe_resolve
from ..kernel.approval import QueueApprover, ToolApprovalRequest
from ..kernel.budget import BudgetGuard
from ..llm.base import LLMClient, LLMResponse, OnChunkCallback
from ..session.store import SessionStore
from ..tools.registry import ToolRegistry

router = APIRouter()

#: WS 生命周期诊断日志（R9）：桌面版唯一可观测出口是 <workspace>/.ra/logs/
#: desktop.log——连接、回合起止与错误帧在此留痕，远端机器的问题不再靠猜。
LOG = logging.getLogger("ra.web.chat")

#: 会话根目录（相对工作区根）。
SESSIONS_SUBDIR = Path(".ra") / "sessions"
#: R12 P2 双轨制：会话模式产物的家（相对工作区根）。任务模式仍写
#: writing_outputs/<ts>_<desc>/，会话产物一律落 outputs/<sid>/——sid 本身
#: 即 YYYYMMDD_HHMMSS_<标题slug>，与零轮次清退可 1:1 配对删除。
OUTPUTS_SUBDIR = Path("outputs")
HISTORY_FILE = "history.json"

MAX_USER_LENGTH = 8_000  # 单条用户消息上限（与前端 slice(0, 8000) 对齐）
MAX_STEER_LENGTH = 2_000  # steer 上限（与 ws.py generate 端点一致）
PREVIEW_LIMIT = 400  # tool_card.result_preview 最大字符数
LAST_MESSAGE_LIMIT = 80  # 会话列表 last_message 摘要长度
ARTIFACT_PATH_LIMIT = 8  # 单张工具卡最多提取的产物文件数
#: 零轮次会话清退时限（§6.4）：POST 建目录后从未收到用户帧的残骸，
#: 超过此时限在列表时整目录删除。远大于 建目录→连 WS→首帧 的正常间隔。
ZERO_TURN_TTL_S = 3600.0

#: 同一会话的并发连接登记表：sid → 当前持有 socket。
#: 并发策略选择「后连者踢前者」：新连接 close 旧 socket（close code 4001），
#: 保证最新 UI 总是活跃端；旧连接的运行经 cancel_event 协作停止，
#: 已落盘的历史不受影响。相比"拒绝新连接"，刷新页面/换标签页体验更好。
_LIVE: dict[str, WebSocket] = {}


# ---------------------------------------------------------------------------
# history.json 读写（D2 唯一权威）
# ---------------------------------------------------------------------------


def _read_history(run_dir: Path) -> list[dict]:
    """容错读取归约历史；损坏/缺失一律返回空列表（不阻塞会话进入）。"""
    path = run_dir / HISTORY_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, list):
        msgs = data  # 容忍裸数组形式
    elif isinstance(data, dict):
        msgs = data.get("messages") or []
    else:
        return []
    return [
        {"role": str(m["role"]), "content": str(m.get("content", ""))}
        for m in msgs
        if isinstance(m, dict) and m.get("role") in ("user", "assistant")
    ]


def _write_history(run_dir: Path, messages: list[dict]) -> None:
    """整份写回历史（唯一权威）。写失败不中断运行（审计仍留有事件）。"""
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "messages": messages}
        (run_dir / HISTORY_FILE).write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 会话目录辅助（REST 与 WS 共用）
# ---------------------------------------------------------------------------


def _sessions_root(cwd: Path) -> Path:
    return Path(cwd) / SESSIONS_SUBDIR


def _outputs_root(cwd: Path) -> Path:
    """会话产物根（双轨制）：``<工作区>/outputs``。"""
    return Path(cwd) / OUTPUTS_SUBDIR


def _slugify(title: str) -> str:
    """从标题派生目录 slug；保留 CJK 以便中文标题可读。"""
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "_", title.strip()[:40]).strip("_")
    return slug or "chat"


def _new_session_dir(root: Path, title: str) -> Path:
    """创建 ``<YYYYMMDD_HHMMSS>_<slug>[_<n>]`` 会话目录并返回。"""
    base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(title)}"
    run_dir = root / base
    n = 1
    while run_dir.exists():  # 同秒重名：追加序号
        n += 1
        run_dir = root / f"{base}_{n}"
    run_dir.mkdir(parents=True)
    return run_dir


def _valid_session_id(name: str) -> bool:
    """会话 ID 即目录名：拒绝路径分隔符与点号目录引用。"""
    return (
        bool(name)
        and name not in (".", "..")
        and "/" not in name
        and "\\" not in name
        and ":" not in name
    )


def _resolve_session_dir(cwd: Path, session_id: str) -> Path:
    """校验并解析会话目录；非法 ID 抛 ValueError，不存在抛 FileNotFoundError。"""
    if not _valid_session_id(session_id):
        raise ValueError(f"会话 ID 不合法: {session_id!r}")
    root = _sessions_root(cwd)
    run_dir = safe_resolve(root / session_id, root)
    if not run_dir.is_dir():
        raise FileNotFoundError(session_id)
    return run_dir


def _load_run_state(run_dir: Path) -> dict | None:
    """容错读取 run.json（列表页只需要 query/timestamps）。"""
    path = run_dir / SessionStore.RUN_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _session_summary(run_dir: Path) -> dict:
    """单条会话摘要（C1 列表项）。turns 定义为历史中的用户消息数。"""
    state = _load_run_state(run_dir) or {}
    messages = _read_history(run_dir)
    last = ""
    for msg in reversed(messages):
        if msg["content"].strip():
            last = msg["content"]
            break
    title = str(state.get("query") or "").strip()
    stat = run_dir.stat()
    return {
        "id": run_dir.name,
        "title": title or None,
        "last_message": last[:LAST_MESSAGE_LIMIT],
        "turns": sum(1 for m in messages if m["role"] == "user"),
        "created_at": state.get("created_at") or stat.st_ctime,
        "updated_at": state.get("updated_at") or stat.st_mtime,
        # 恢复期兜底（权威源是 connected 帧）：B4 之前的旧会话为 None
        "outputs_dir": state.get("outputs_dir") or None,
    }


# ---------------------------------------------------------------------------
# C1: 会话 REST（app.py 以 prefix="/api" 挂载本 router）
# ---------------------------------------------------------------------------


def _cwd_of(request_or_ws) -> Path:
    """工作区根：lifespan 写入的 app.state.cwd，缺省回退进程 CWD。"""
    return getattr(request_or_ws.app.state, "cwd", None) or Path.cwd()


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


def _sweep_zero_turn_sessions(root: Path, outputs_root: Path | None = None) -> None:
    """列表前清退零轮次且过期的会话目录（§6.4 空会话治理）。

    安全性：用户消息在回合开始前先落盘（_run_turn），因此「history.json
    无用户消息」严格等价于「从未收到任何用户帧」——只可能是 POST 建目录后
    连接失败 / 应用被杀的残骸，整目录删除不丢对话内容。TTL 保护刚建目录、
    尚在连 WS 的 in-flight 会话。清退失败静默跳过（下次列表再试）。
    R12 P2 双轨制：产物目录与会话 1:1（outputs/<sid>），清退时配对删除；
    零轮次 ⇒ 从未运行过工具 ⇒ 产物目录内不可能有用户数据。孤立的
    outputs 目录（会话目录已不在）不主动追删——惰性无害，避免误删。
    """
    if not root.is_dir():
        return
    if outputs_root is None:
        outputs_root = root.parent.parent / OUTPUTS_SUBDIR
    now = time.time()
    for child in root.iterdir():
        try:
            if not child.is_dir() or child.name.startswith("."):
                continue
            state = _load_run_state(child)
            if state is None:
                continue  # 与 list 的准入口径一致：无 run.json 不算会话
            age = now - (state.get("updated_at") or child.stat().st_mtime)
            if age <= ZERO_TURN_TTL_S:
                continue
            if any(m["role"] == "user" for m in _read_history(child)):
                continue
            shutil.rmtree(child, ignore_errors=True)
            shutil.rmtree(outputs_root / child.name, ignore_errors=True)
        except OSError:
            continue


@router.get("/chat/sessions")
async def list_sessions(request: Request):
    """全部会话摘要，按 updated_at 倒序（最近活跃在前）。

    零轮次且超过 ZERO_TURN_TTL_S 的残骸目录先被清退（§6.4）。
    """
    root = _sessions_root(_cwd_of(request))
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
    items.sort(key=lambda item: item.get("updated_at") or 0, reverse=True)
    return items


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


@router.delete("/chat/sessions/{session_id}")
async def delete_session(session_id: str, request: Request):
    """删除整个会话目录（含 run/events/history）。"""
    try:
        run_dir = _resolve_session_dir(_cwd_of(request), session_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="会话 ID 不合法") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    shutil.rmtree(run_dir, ignore_errors=True)
    # R12 P2 双轨制：产物目录 1:1 归会话所有，显式删除时一并清掉
    shutil.rmtree(_outputs_root(_cwd_of(request)) / session_id, ignore_errors=True)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 适配层：既往对话注入 + 产物提取 + 系统指令
# ---------------------------------------------------------------------------


class _HistoryClient(LLMClient):
    """LLM client 包装层：把 history.json 的归约历史前置进本轮首个请求。

    内核 ``run_agent`` 每次都从全新 ``messages=[user prompt]`` 起步，没有
    初始历史参数（内核缺口见回报）。多轮连续对话由本包装完成：当检测到
    「本轮首条请求」的形态（messages 恰为单条 user 消息）时，把前缀历史
    拼接在最前。用形状判断而非一次性标志，是为了让首条请求的重试
    （_llm_call_with_retry）也能同样展开；同轮后续调用消息数必然 >1，
    不受影响。预算/用量按真实（含历史的）请求计量，无失真。
    """

    def __init__(self, inner: LLMClient) -> None:
        super().__init__()
        self._inner = inner
        self._prefix: list[dict] = []

    @property
    def model(self) -> str:
        return getattr(self._inner, "model", "")

    @property
    def prefix(self) -> list[dict]:
        return self._prefix

    def set_prefix(self, messages: list[dict]) -> None:
        """每轮开始前设置要注入的既往对话（不含刚追加的用户消息）。"""
        self._prefix = list(messages)

    async def chat(  # noqa: D102 — 形参与 LLMClient.chat 保持一致
        self,
        messages: list[dict],
        *,
        system: str = "",
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        on_chunk: OnChunkCallback | None = None,
        on_activity: Any | None = None,
    ) -> LLMResponse:
        if self._prefix and len(messages) == 1 and messages[0].get("role") == "user":
            messages = [*self._prefix, *messages]
        return await self._inner.chat(
            messages,
            system=system,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            on_chunk=on_chunk,
            on_activity=on_activity,
        )

    async def close(self) -> None:
        await self._inner.close()


#: 从自由文本中启发式提取产物路径（run_python/bash 结果）的正则。
#: 匹配以常见产物扩展名结尾、不含空白与常见标点的 token；
#: 允许 Windows 盘符前缀（如 D:\x\y.png）。
_ARTIFACT_RE = re.compile(
    r"[^\s\"'`<>()\[\]{};,]+\.(?:png|jpe?g|gif|svg|webp|pdf|docx|doc|csv|xlsx?"
    r"|md|bib|tex|json|html?)",
    re.IGNORECASE,
)


def extract_artifact_paths(
    tool_name: str,
    arguments: dict | None,
    result_text: str,
    limit: int = ARTIFACT_PATH_LIMIT,
) -> list[dict]:
    """从一次工具调用中提取产物文件路径（纯函数，C4 files[] 规则）。

    规则：
    - write_file/edit_file：直接取 arguments.file_path（写入即产物）；
    - bash/run_python：对结果文本做扩展名启发式扫描（figures/*.png 等）；
    - 被拒绝或报错的调用不提取（没有可信产物）；
    - 去重保序，最多 *limit* 条；帧格式为 ``[{"path": "..."}]``。
    """
    paths: list[str] = []
    text = result_text if isinstance(result_text, str) else str(result_text)
    if not text.startswith(("Error", "[DENIED")):
        args = arguments if isinstance(arguments, dict) else {}
        file_path = str(args.get("file_path") or "")
        if tool_name in ("write_file", "edit_file") and file_path:
            paths.append(file_path)
        if tool_name in ("bash", "run_python"):
            paths.extend(m.group(0) for m in _ARTIFACT_RE.finditer(text))
    seen: set[str] = set()
    out: list[dict] = []
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        out.append({"path": p})
        if len(out) >= limit:
            break
    return out


def _chat_system_instructions(work_dir: Path, outputs_dir: Path | None = None) -> str:
    """WRITER.md 基座 + 会话模式附录（R8 反馈 #4：cowork 化）。

    R12 P2 双轨制口径：*work_dir* 是工作区共享根（读共享数据），*outputs_dir*
    是本会话产物目录（写产物 + 执行默认 CWD）——两个绝对路径都明示给模型，
    相对路径写入会被自动归巢到产物目录。结尾追加执行契约附录
    （execution_contract_addendum）：打包版在此声明「没有独立 Python，
    一切经 run_python / run_script」。
    """
    base = load_system_instructions(work_dir)
    if outputs_dir is None:
        outputs_dir = work_dir
    return (
        base
        + f"""

## 会话模式补充指令（cowork mode）

你是与用户并肩工作的 agent：能动手就直接动手，交付看得见的产物，而不是只给建议。

**执行原则**
- 本工作区的根目录是 {work_dir}；本会话的专属产物目录是 {outputs_dir}。
- 读写分工：产出文件（图表、文档、脚本、数据结果）一律放进产物目录——相对路径写入会自动落到那里，bash/run_python 的默认工作目录也是它；读取工作区里的既有共享数据（data/、sources/ 等）时用**绝对路径**（可拼接全局常量 WS，它就是 {work_dir}）。
- 写出的文件会自动以卡片展示、可预览——优先把工作成果落成文件。
- 能用工具完成的事不要停留在口头描述：读数据、跑分析、画图、写文档，直接做，完成后简要汇报结果与产物路径。
- 用户每发一条消息，回复一轮即停下等下一条；除非用户明确要求连续产出长文档，不要自行连写。
- 遇到需要多步的请求（如"帮我整理这批数据并出报告"），先给一句两三步的计划，然后在本轮内直接执行到底。

**产物规范（重要）**
- 所有产物写入上面的专属产物目录；不要写进 writing_outputs/（那是任务模式的领地），也不要散落在工作区根。
- 用 run_python 生成 matplotlib 图表时保存为 PNG 到产物目录，并在回复中给出文件名。
- 回合结束时若本轮产出了文件，在回复末尾附「交付物」清单：每行一个相对产物目录的路径加一句说明。

**引用纪律**
- 引用文献时只使用真实可查证的论文，禁止编造 DOI 或参考文献；不确定就说明不确定。

**语言与风格**
- 用用户的语言回复；正文简洁，可用 Markdown。
"""
        + execution_contract_addendum()
    )


def _jsonable_arguments(args: dict | None) -> dict:
    """工具卡 arguments 保证可 JSON 序列化（不可序列化时降级为 repr 文本）。"""
    if not isinstance(args, dict):
        return {}
    try:
        json.dumps(args)
        return args
    except (TypeError, ValueError):
        return {"repr": repr(args)[:400]}


#: 网络类错误附带的可行动指引（R9：端点不可达曾表现为永久「思考中」，
#: 错误帧必须告诉用户下一步做什么，而不是一句裸异常文本）。
_NETWORK_HINT = (
    "——无法连接模型端点。请检查：① Base URL 是否正确（设置页「测试连接」可验证）；"
    "② 本机网络能否直连该端点——境内服务请确认代理已关闭，"
    "境外服务需网络可达或设置 HTTPS_PROXY 环境变量后重启应用。"
)


def _is_network_error(exc: BaseException) -> bool:
    """连接失败/超时类错误的宽松识别（用于追加用户指引，不影响重试逻辑）。"""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    name_keys = ("connect", "timeout", "ssl", "socket", "network")
    text_keys = (
        "connect",
        "timed out",
        "timeout",
        "ssl",
        "socket",
        "network",
        "unreachable",
        "refused",
        "reset by peer",
    )
    return any(k in name for k in name_keys) or any(k in text for k in text_keys)


# ---------------------------------------------------------------------------
# C2/C3/C4: WS /ws/chat — 会话循环
# ---------------------------------------------------------------------------


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket, session: str | None = None):
    """通用 agentic 会话端点。

    server→client / client→server 全部帧型见 docs/protocol.md
    「§ 会话协议 (/ws/chat)」。断连即取消（cancel_event），与 ws.py 同构。
    """
    await websocket.accept()

    cancel_event = asyncio.Event()  # 断连兜底：任何阶段置位都终止底层运行
    send_lock = asyncio.Lock()  # 多任务共用一个 socket，串行化发送帧
    sid = ""
    llm_client: _HistoryClient | None = None

    async def _send(frame: dict) -> bool:
        """发一帧；断连后静默失败（由 receive 端感知断连），返回是否成功。"""
        try:
            async with send_lock:
                await websocket.send_json(frame)
            return True
        except Exception:
            return False

    try:
        cwd = _cwd_of(websocket)
        root = _sessions_root(cwd)

        # ---- 定位或新建会话目录 ------------------------------------------
        if session:
            candidate = session.strip()
            if not _valid_session_id(candidate):
                await _send({"type": "error", "message": "会话 ID 不合法"})
                await websocket.close()
                return
            # 目录不存在时按同名自动重建（幂等进入：删除后的会话可无缝再开）
            run_dir = root / candidate
            run_dir.mkdir(parents=True, exist_ok=True)
            try:
                safe_resolve(run_dir, root)
            except ValueError:  # 符号链接等越界：与 _valid_session_id 双保险
                await _send({"type": "error", "message": "会话 ID 不合法"})
                await websocket.close()
                return
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
            await websocket.close()
            return
        if store.state.outputs_dir != f"outputs/{sid}":
            store.state.outputs_dir = f"outputs/{sid}"  # 相对 POSIX，权威在帧
            store.save()

        # ---- 并发连接：踢掉同会话旧 socket --------------------------------
        previous = _LIVE.get(sid)
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=4001, reason="replaced by newer connection")
            except Exception:
                pass
        _LIVE[sid] = websocket

        # ---- 组装循环依赖（照 ws.py generate 的方式） ----------------------
        approvals: asyncio.Queue = asyncio.Queue()
        steers: asyncio.Queue = asyncio.Queue()
        # 连接期仅确定预算的初始计价模型；LLM 客户端改为**每轮实时构建**
        # （见 _run_turn 开头）。不能用 lifespan 的 app.state.model 快照——
        # 它会把「启动时未配置而回退的默认模型名」永久钉死在会话上；
        # 也不能只在连接时构建一次——那样设置页保存的新 Key/模型对已打开
        # 的会话永远不生效（R7 反馈 #3 主因 + 残留路径一并修掉）。
        budget = BudgetGuard(model=resolve_model(None))  # limits 自 RA_MAX_* 继承
        # 双轨制注入：sandbox 围栏恒为工作区根；相对写入与执行默认 CWD 归巢
        # 产物目录（savefig 相对保存自动落家）；读共享数据靠契约里的绝对路径口径。
        tools = ToolRegistry(
            work_dir=str(cwd),
            write_anchor=str(outputs_abs),
            exec_cwd=str(outputs_abs),
        )
        system_instructions = _chat_system_instructions(cwd, outputs_abs)

        ask_state = {"current": ""}  # 当前待应答的审批请求 ID（防迟到回执污染）

        def _push_approval(req: ToolApprovalRequest) -> None:
            ask_id = uuid.uuid4().hex[:8]
            ask_state["current"] = ask_id
            asyncio.get_running_loop().create_task(
                _send(
                    {
                        "type": "approval_request",
                        "id": ask_id,
                        "tool": req.tool_name,
                        "summary": req.summary(),
                    }
                )
            )

        approver = QueueApprover(approvals, timeout=120.0, on_request=_push_approval)

        tasks_reg = getattr(websocket.app.state, "active_tasks", None)
        if isinstance(tasks_reg, dict):  # 注册到任务表：REST stop 可达（可选能力）
            tasks_reg[f"chat:{sid}"] = {
                "status": "running",
                "query": sid[:100],
                "cancel_event": cancel_event,
                "approvals": approvals,
                "steers": steers,
            }

        card_seq = itertools.count(1)  # 卡片 ID 连接内唯一（跨轮不重置：
        pending_cards: deque[str] = deque()  # 前端 cards 映射按 id 合并）

        async def _on_text(delta: str) -> None:
            # 流式路径：run_agent 把该回调作为 on_chunk 传给 LLM client，
            # 因此这里是逐段增量而非整轮文本。
            if delta:
                await _send({"type": "text", "delta": delta})

        async def _on_tool_start(tool: str, args: dict) -> None:
            cid = f"c{next(card_seq)}"
            pending_cards.append(cid)  # 工具顺序执行：FIFO 配对结束回调
            await _send(
                {
                    "type": "tool_card",
                    "id": cid,
                    "tool": tool,
                    "arguments": _jsonable_arguments(args),
                    "status": "running",
                    "result_preview": "",
                    "files": [],
                }
            )

        async def _on_tool_use(tool: str, args: dict, result: object) -> None:
            text = result if isinstance(result, str) else str(result)
            # 被拒/出错的调用不会触发 on_tool_start，这里兜底补发终态卡
            cid = pending_cards.popleft() if pending_cards else f"c{next(card_seq)}"
            status = "error" if text.startswith(("Error", "[DENIED")) else "done"
            await _send(
                {
                    "type": "tool_card",
                    "id": cid,
                    "tool": tool,
                    "arguments": _jsonable_arguments(args),
                    "status": status,
                    "result_preview": text[:PREVIEW_LIMIT],
                    "files": extract_artifact_paths(tool, args, text),
                }
            )

        async def _run_turn(text: str) -> None:
            """一轮完整对话：载入历史 → 追加用户消息 → run_agent → 写回。"""
            nonlocal llm_client
            turn_t0 = time.monotonic()
            cancel_event.clear()  # 新回合重置上一轮遗留的停止信号
            # ---- 每轮实时构建客户端：设置页保存 / 工作区切换即刻生效 -------
            model_now = resolve_model(None)
            budget.model = model_now  # 计价跟随实际模型，预算口径不漂移
            try:
                fresh_client = _HistoryClient(build_llm_client(model=model_now))
            except ValueError as exc:  # 未配置 Key 等 → 错误帧收场，不踢连接
                store.finish("failed", budget.snapshot())
                LOG.warning("回合配置缺失 sid=%s：%s", sid, exc)
                await _send({"type": "error", "message": str(exc)})
                return
            if llm_client is not None:  # 释放上一轮客户端，防连接句柄泄漏
                try:
                    await llm_client.close()
                except Exception:
                    pass
            llm_client = fresh_client

            messages = _read_history(run_dir)
            messages.append({"role": "user", "content": text})
            _write_history(run_dir, messages)  # 用户消息先落盘（崩溃可恢复）
            store.save()  # 刷新 run.json updated_at
            store.log_event("turn_start", {"chars": len(text)})
            LOG.info("回合开始 sid=%s 字数=%d 模型=%s", sid, len(text), model_now)
            llm_client.set_prefix(messages[:-1])  # 注入既往对话（适配层）

            async def _invoke():
                return await run_agent(
                    prompt=text,
                    system_prompt=system_instructions,
                    llm_client=llm_client,
                    tools=tools,
                    config=RunConfig(
                        # 会话语义：一条用户消息一轮回复，自然停即停。
                        # 截断续跑不受影响——max_tokens 分支由内核自行注入
                        # "Continue from where you left off."，长文档产出仍连贯。
                        auto_continue=False,
                        budget=budget,
                        cancel_event=cancel_event,
                        approver=approver,
                        session_log=store,  # events.jsonl 审计镜像（msg_add 等）
                    ),
                    on_text=_on_text,
                    on_tool_start=_on_tool_start,
                    on_tool_use=_on_tool_use,
                    steer_queue=steers,
                )

            agent_task = asyncio.ensure_future(_invoke())
            try:
                # B5 思路复用：运行期每 ~1s 推一帧 usage 快照，结束时至少一帧。
                async for frame in usage_ticks(agent_task, budget):
                    if not await _send(frame):
                        break  # 断连：usage_ticks 会兜底硬停 agent_task
                agent_result = agent_task.result()
            except asyncio.CancelledError:
                # 真·取消（断连硬停/服务关闭）：状态落盘后交还控制权，
                # 由主循环的 receive 感知断连收尾。
                store.finish("cancelled", budget.snapshot())
                return
            except Exception as exc:
                store.finish("failed", budget.snapshot())
                message = str(exc) + (_NETWORK_HINT if _is_network_error(exc) else "")
                LOG.warning("回合失败 sid=%s 用时=%.1fs：%s",
                            sid, time.monotonic() - turn_t0, str(exc)[:300])
                await _send({"type": "error", "message": message})
                return

            reply = (agent_result.text_output or "").strip()
            if reply:
                messages.append({"role": "assistant", "content": reply})
                _write_history(run_dir, messages)
            # stop 动作/断连取消时内核正常返回，stop_reason=cancelled —— 状态如实落盘
            final_status = "cancelled" if agent_result.stop_reason == "cancelled" else "complete"
            LOG.info("回合结束 sid=%s 状态=%s 用时=%.1fs 轮次=%s",
                     sid, final_status, time.monotonic() - turn_t0, agent_result.turns)
            store.finish(final_status, budget.snapshot())
            await _send(
                {
                    "type": "result",
                    "stop_reason": agent_result.stop_reason,
                    "turns": agent_result.turns,
                }
            )

        async def _dispatch(msg: dict) -> None:
            """处理非 user 类动作：审批回执 / steer / stop（泵与空闲态共用）。"""
            action = msg.get("action")
            if action == "approval":
                ask_id = str(msg.get("id") or "")
                if ask_id and ask_id == ask_state["current"]:
                    ask_state["current"] = ""
                    approvals.put_nowait(bool(msg.get("approved")))
                # 迟到 / 未知 id 的回执直接忽略：避免残留答案自动应答下一次问询
            elif action == "steer":
                message = str(msg.get("message") or "").strip()
                if not message:
                    await _send({"type": "error", "message": "steer 内容不能为空"})
                elif len(message) > MAX_STEER_LENGTH:
                    await _send(
                        {
                            "type": "error",
                            "message": f"steer 过长（最大 {MAX_STEER_LENGTH} 字符）",
                        }
                    )
                else:
                    steers.put_nowait(message)
            elif action == "stop":
                cancel_event.set()
            elif action == "user":
                # 容忍运行中误发的 user 动作：按 steer 处理（与前端行为一致）
                message = str(msg.get("text") or "").strip()
                if message:
                    steers.put_nowait(message[:MAX_STEER_LENGTH])
            else:
                await _send({"type": "error", "message": f"未知 action: {action}"})

        async def _pump() -> None:
            """轮次运行期间持续接收客户端消息并分发。"""
            try:
                while True:
                    await _dispatch(await websocket.receive_json())
            except Exception:
                # 断连 / 解析失败：取消本轮运行，并解除阻塞中的审批问询
                cancel_event.set()
                approvals.put_nowait(None)

        LOG.info("会话连接建立 sid=%s outputs=%s", sid, store.state.outputs_dir)
        # connected 帧是前端 dock 的权威源：REST 列表在工作区切换后会把
        # dock 错接到另一工作区的同名目录，这里以本连接的 cwd 为准。
        await _send({
            "type": "connected",
            "session_id": sid,
            "outputs_dir": store.state.outputs_dir,
        })

        # ---- 主循环：空闲期直接接收，user 动作触发一轮 ---------------------
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
                    pump = asyncio.create_task(_pump())
                    try:
                        await _run_turn(text)
                    finally:
                        pump.cancel()
                        # 注意：不能直接 ``await pump`` —— 被取消的任务会把
                        # CancelledError（BaseException）抛进本协程并杀掉连接；
                        # asyncio.wait 只等状态不传播任务异常。
                        try:
                            await asyncio.wait({pump})
                        except Exception:
                            pass
            else:
                await _dispatch(msg)

    except WebSocketDisconnect:
        # 客户端离开 —— 确保底层运行停止消耗 token（与 ws.py 同构）
        LOG.info("会话连接断开 sid=%s", sid)
        cancel_event.set()
    except Exception as exc:
        LOG.warning("会话连接异常 sid=%s：%s", sid, str(exc)[:300])
        await _send({"type": "error", "message": str(exc)})
    finally:
        if sid:
            if _LIVE.get(sid) is websocket:
                _LIVE.pop(sid, None)
            tasks_reg = getattr(websocket.app.state, "active_tasks", None)
            if isinstance(tasks_reg, dict):
                tasks_reg.pop(f"chat:{sid}", None)
        if llm_client is not None:
            try:
                await llm_client.close()
            except Exception:
                pass
