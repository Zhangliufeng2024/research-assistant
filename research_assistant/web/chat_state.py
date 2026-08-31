"""会话状态与目录/历史 IO（工程债拆分，2026-08-31）。

从 ``web/chat.py`` 抽出：模块级注册表（墓碑/连接/回合/会话）、会话目录解析、
history.json 读写、零轮次清退与守卫版 SessionStore。运行时（ws_chat、_start_turn）
与 REST CRUD 仍留在 chat.py，经本模块共享同一份状态对象。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core import atomic_write_text, safe_resolve
from ..session.store import SessionStore
from ..session.store import load_run_state as _load_run_state

LOG = logging.getLogger("ra.web.chat")
SESSIONS_SUBDIR = Path(".ra") / "sessions"
OUTPUTS_SUBDIR = Path("outputs")
HISTORY_FILE = "history.json"
LAST_MESSAGE_LIMIT = 80
ZERO_TURN_TTL_S = 3600.0
DELETE_SETTLE_TIMEOUT_S = 8.0
FRAME_RING_CAP = 4000

_TOMBSTONES: set[str] = set()
_LIVE: dict[str, Any] = {}
_SINKS: dict[str, Any] = {}
_SESSIONS: dict[str, dict] = {}
_ACTIVE: dict[str, Any] = {}

_IMAGE_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


@dataclass
class _TurnHandle:
    """一个活动/刚结束回合的全部可迁移状态——连接断了，回合照跑。

    并发模型：全部字段只在事件循环协程内读写；所有 check-then-act 都落在
    无 await 的同步段（_start_turn 独占创建、_turn_main 独占收尾、观察者
    增减在同步辅助函数内），因此 dict 与字段都不需要锁。
    """

    task: Any = None                  # asyncio.Task[_turn_main]
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    budget: Any = None                # BudgetGuard（会话级共享，跨回合累计）
    approvals: asyncio.Queue = field(default_factory=asyncio.Queue)
    #: Plan 门（方案 1）的裁决队列：plan_decision 回执入此，_wait_plan_decision
    #: 消费。与工具审批队列分开——两类问询永不同回合并存（planner 无工具），
    #: 分队列可避免迟到回执串道。
    plans: asyncio.Queue = field(default_factory=asyncio.Queue)
    steers: asyncio.Queue = field(default_factory=asyncio.Queue)
    approver: Any = None              # QueueApprover（per-turn 装配）
    ask_state: dict = field(default_factory=lambda: {"current": "", "plan": ""})
    frames: deque = field(default_factory=deque)  # 已发射帧（含 seq），回放源
    #: 帧序号游标——**会话内单调**，新建句柄时从上一回合句柄续接（见
    #: _start_turn）。前端以收到的最大 seq 作断线重连的 attach 游标，服务端
    #: 按 seq>after 过滤回放；若每回合从 1 重来，重连后错过的帧会被旧游标
    #: 永久滤掉（真实浏览器 E2E 抓出的缺陷，单回合协议测试覆盖不到）。
    seq: int = 0
    partial_text: str = ""            # on_text 增量累积——异常/硬取消时的兜底文本
    status: str = "running"           # running | complete | failed | cancelled
    observers: int = 0                # 观察者连接数（孤儿看门狗的触发依据）
    orphan_task: Any = None           # 看门狗任务（有人观察时为 None）
    feeder: Any = None                # usage_ticks 泵任务

    def next_seq(self, frame: dict) -> dict:
        """登记一帧：注入自增 seq、入环形缓冲（超限丢最旧），返回发送体。"""
        self.seq += 1
        out = dict(frame)
        out["seq"] = self.seq
        self.frames.append(out)
        if len(self.frames) > FRAME_RING_CAP:
            self.frames.popleft()
        return out


def _slugify(title: str) -> str:
    """从标题派生目录 slug；保留 CJK 以便中文标题可读。"""
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "_", title.strip()[:40]).strip("_")
    return slug or "chat"


def _cwd_of(request_or_ws) -> Path:
    """工作区根：lifespan 写入的 app.state.cwd，缺省回退进程 CWD。"""
    return getattr(request_or_ws.app.state, "cwd", None) or Path.cwd()


def _sessions_root(cwd: Path) -> Path:
    return Path(cwd) / SESSIONS_SUBDIR


def _outputs_root(cwd: Path) -> Path:
    """会话产物根（双轨制）。

    R17 迁移期兼容：``.ra/outputs/`` 已存在（迁移脚本搬迁完成）则优先
    使用新位置，否则回退旧的 ``<工作区>/outputs``——一个版本过渡期后
    旧路径可下线。新会话产物始终写返回的根。
    """
    migrated = Path(cwd) / ".ra" / "outputs"
    if migrated.is_dir():
        return migrated
    return Path(cwd) / OUTPUTS_SUBDIR


def _new_session_dir(root: Path, title: str) -> Path:
    """创建 ``<YYYYMMDD_HHMMSS>_<slug>[_<n>]`` 会话目录并返回。"""
    base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(title)}"
    run_dir = root / base
    n = 1
    while run_dir.exists():  # 同秒重名：追加序号
        n += 1
        run_dir = root / f"{base}_{n}"
    run_dir.mkdir(parents=True)
    if run_dir.name in _TOMBSTONES:
        # 同秒同 slug 的名字再生（删除后 <1s 内新建同名会话）：新化身接管
        # 该名字，旧墓碑随之失效——否则新会话的一切落盘会被误拦甚至被自删。
        # 迟到写回不经过本函数，幽灵拦截不受影响。
        _TOMBSTONES.discard(run_dir.name)
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


def _blocked_by_tombstone(run_dir: Path) -> bool:
    """写回点共用的墓碑检查；命中返回 True 并顺手自删残留目录。

    自删（ignore_errors）是对「目录已被其他写回路径重建」的兜底清理：
    多数情况下目录早已被 delete_session 移除，此时 rmtree 是无害空操作。
    """
    if run_dir.name not in _TOMBSTONES:
        return False
    shutil.rmtree(run_dir, ignore_errors=True)
    return True


def _read_history(run_dir: Path) -> list[dict]:
    """容错读取归约历史；损坏留档后按空历史继续（不阻塞会话进入）。

    半截 JSON（断电/崩溃残留）若被静默当作空历史，下一回合的整份写回
    会把原对话永久清零——因此先把坏文件改名留档（证据可追溯），再返回
    空列表。留档改名失败（文件被占用等）则放弃留档但不抛出。
    """
    path = run_dir / HISTORY_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return []  # 读失败（占用/权限）：与缺失同等对待，不阻塞会话
    except json.JSONDecodeError as exc:
        backup = run_dir / f"{HISTORY_FILE}.corrupt.{int(time.time())}"
        if backup.exists():  # 同秒多次损坏：追加纳秒避免覆盖前一份留档
            backup = run_dir / f"{HISTORY_FILE}.corrupt.{time.time_ns()}"
        try:
            path.rename(backup)
            LOG.warning("历史文件损坏已留档 %s -> %s：%s",
                        path, backup.name, exc)
        except OSError as rename_exc:
            LOG.warning("历史文件损坏且留档失败 %s：%s", path, rename_exc)
        return []
    if isinstance(data, list):
        msgs = data  # 容忍裸数组形式
    elif isinstance(data, dict):
        msgs = data.get("messages") or []
    else:
        return []

    # 归一化的同时必须**透传结构化扩展字段**（R16）：attachments（UI 渲染
    # 徽章）与 partial=True（被打断的回答标记）。此前这里把条目投影成裸
    # {role, content}，而收尾写回走「读→追加→整份写」——等于每回合结束
    # 都对历史做一次清洗，扩展字段全部蒸发（真实浏览器 E2E 抓出）。
    out: list[dict] = []
    for m in msgs:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            continue
        entry: dict = {"role": str(m["role"]), "content": str(m.get("content", ""))}
        raw_atts = m.get("attachments")
        if isinstance(raw_atts, list) and raw_atts:
            clean_atts = [
                _normalize_attachment(a)
                for a in raw_atts
                if isinstance(a, dict)
            ]
            clean_atts = [a for a in clean_atts if a]
            if clean_atts:
                entry["attachments"] = clean_atts
        if m.get("partial") is True:
            entry["partial"] = True
        out.append(entry)
    return out


def _write_history(run_dir: Path, messages: list[dict]) -> None:
    """整份写回历史（唯一权威）。写失败不中断运行（审计仍留有事件）。

    经 core.atomic_write_text 原子替换（同目录临时文件 + fsync +
    os.replace）：断电/崩溃不会留下半截 JSON——半截历史会被下一回合
    误读为损坏而清零对话。
    幽灵会话拦截（A3）：会话已删除（墓碑命中）时放弃写回并自删残留——
    迟到的收尾写回不得把已删除的会话目录重建回来。
    """
    if _blocked_by_tombstone(run_dir):
        return
    try:
        payload = {"schema_version": 1, "messages": messages}
        atomic_write_text(
            run_dir / HISTORY_FILE,
            json.dumps(payload, ensure_ascii=False),
        )
    except OSError:
        # 真实错误上报：历史写回失败意味着对话记录丢失，静默会掩盖数据损坏
        LOG.warning("会话历史写回失败 run_dir=%s", run_dir, exc_info=True)


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
            if child.name in _TOMBSTONES:
                # 墓碑会话归删除端点负责（可能仍在等回合退出）：清退不得
                # 介入，避免与 delete_session 的 rmtree 竞争同一目录。
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


class _GuardedSessionStore(SessionStore):
    """墓碑感知的 SessionStore：已删除会话的 run_state / events 写回一律放弃。

    会话模式的全部 run.json / events.jsonl 落盘都经 save() / finish() /
    log_event() 三个口子，在此统一拦截即可覆盖收尾路径的全部写回点。
    不改 ws_chat/_run_turn 一行的关键在于：函数体内的 ``SessionStore(...)``
    名字解析发生在**调用期**（模块全局查找），因此只需在模块级把该名字
    重绑到本子类（见类定义之后的赋值），ws_chat 拿到的即是守卫子类；
    任务模式等其他模块直接从 session.store import 原类，不受影响。
    """

    def _blocked(self) -> bool:
        return _blocked_by_tombstone(self.run_dir)

    def save(self) -> None:  # noqa: D102 — 语义与父类一致，仅加墓碑短路
        if self._blocked():
            return
        super().save()

    def log_event(self, kind: str, data: dict | None = None) -> None:  # noqa: D102
        if self._blocked():
            return
        super().log_event(kind, data)

    def finish(self, status: str, budget_snapshot: dict | None = None) -> None:  # noqa: D102
        if self._blocked():
            return
        super().finish(status, budget_snapshot)


def _guess_image_mime(name: str) -> str | None:
    """按扩展名猜图片 mime；非图片扩展名返回 None。"""
    return _IMAGE_MIME_BY_EXT.get(Path(name).suffix.lower())


def _normalize_attachment(a: dict) -> dict | None:
    """历史归一化用：附件条目保留 name/path，图片类附件补留 mime_type。"""
    path = str(a.get("path", ""))
    if not path and not a.get("name"):
        return None
    entry: dict = {"name": str(a.get("name", "")), "path": path}
    mime = str(a.get("mime_type", "")) or _guess_image_mime(entry["name"] or path)
    if mime:
        entry["mime_type"] = mime
    return entry


#: 重绑模块内名字：让会话运行时调用期的 ``SessionStore`` 解析到守卫子类
#: （原理见 _GuardedSessionStore 类注释；最小侵入的墓碑接线点）。
SessionStore = _GuardedSessionStore
