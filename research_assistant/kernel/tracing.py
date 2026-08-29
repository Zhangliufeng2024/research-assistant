"""执行链路 tracing（G-6）：HookBus 生命周期事件 → JSONL span 流。

设计取舍（刻意保持零依赖、零开销可关）：

* **零新依赖**：不引入 opentelemetry——直接订阅 HookBus 的生命周期事件，
  把每条事件写成一行 JSON（JSONL）。产物用任何 ``jq``/文本工具即可消费。
* **配对成 span**：LLM_REQUEST→LLM_RESPONSE 按 turn 配对、
  TOOL_START→TOOL_END 按 (turn, tool_name) FIFO 配对（同回合同名工具
  可能多次调用），在结束事件行上回填 ``duration_ms``。
* **零开销开关**：``RA_TRACE_DIR`` 未设置时 :func:`maybe_attach_tracing`
  返回 None、不注册任何 handler——热路径上只有一次 ``os.getenv``。
* **异常收尾**：内核在错误路径会补发 RUN_END（agent.py 缺陷 A 修复），
  但为防御只发 ERROR 就断掉的路径，recorder 在收到 ERROR 且 run 尚未
  收尾时补写一条 ``run_end``（stop_reason="error"）。

JSONL 行格式（每行一个对象）::

    {"ts": 1787..., "event": "llm_response", "turn": 2,
     "tool": "", "duration_ms": 1234.5, "payload": {...摘要...}}
"""

from __future__ import annotations

import json
import os
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from .events import AgentEvent, EventKind, HookBus, HookVerdict

#: 摘要里字符串载荷的最大保留长度（防超长 arguments/错误刷爆 trace 文件）
_SUMMARY_STR_LIMIT = 300

#: 订阅的事件种类（含配对所需的 TOOL_START 与异常收尾所需的 ERROR）
_TRACED_KINDS = (
    EventKind.RUN_START,
    EventKind.TURN_START,
    EventKind.LLM_REQUEST,
    EventKind.LLM_RESPONSE,
    EventKind.PRE_TOOL_USE,
    EventKind.TOOL_START,
    EventKind.TOOL_END,
    EventKind.ERROR,
    EventKind.RUN_END,
)


def _summarize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """把事件载荷裁成可落盘的摘要：字符串截断、嵌套只留标量。"""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            out[key] = value[:_SUMMARY_STR_LIMIT]
        elif isinstance(value, (int, float, bool)) or value is None:
            out[key] = value
        else:
            out[key] = str(value)[:_SUMMARY_STR_LIMIT]
    return out


class TraceRecorder:
    """把 HookBus 事件流写成 JSONL 的同步 handler（订阅见 attach_tracing）。

    HookBus 的 handler 允许同步函数且异常被吞掉告警——落盘失败（磁盘满、
    权限）不应影响 agent 循环，这里不额外抛错，只在构造时打开一次文件
    句柄（append 模式），每行写后即落。
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("a", encoding="utf-8")
        #: LLM_REQUEST 的 turn → 起始 ts（AgentEvent.ts 为 time.time 口径）
        self._llm_started: dict[int, float] = {}
        #: TOOL_START 的 (turn, tool_name) → 起始 ts 队列（同名工具 FIFO 配对）
        self._tool_started: dict[tuple[int, str], deque[float]] = {}
        self._run_open = False
        self._run_end_written = False

    def _write(self, event: AgentEvent, *, duration_ms: float | None = None) -> None:
        record: dict[str, Any] = {
            "ts": round(event.ts, 3),
            "event": event.kind.value,
            "turn": event.turn,
            "tool": event.tool_name,
            "payload": _summarize_payload(event.payload),
        }
        if duration_ms is not None:
            record["duration_ms"] = round(duration_ms, 3)
        try:
            self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._fh.flush()
        except (OSError, ValueError, TypeError):
            pass  # 落盘尽力而为：trace 故障绝不干扰 agent 循环

    def handle(self, event: AgentEvent) -> HookVerdict | None:
        """HookBus handler 入口：按事件种类配对计时并落盘（恒不拦截）。"""
        kind = event.kind
        if kind is EventKind.RUN_START:
            self._run_open = True
            self._run_end_written = False
            self._write(event)
        elif kind is EventKind.TURN_START:
            self._write(event)
        elif kind is EventKind.LLM_REQUEST:
            self._llm_started[event.turn] = event.ts
            self._write(event)
        elif kind is EventKind.LLM_RESPONSE:
            start = self._llm_started.pop(event.turn, None)
            duration = (event.ts - start) * 1000.0 if start is not None else None
            self._write(event, duration_ms=duration)
        elif kind is EventKind.PRE_TOOL_USE:
            self._write(event)
        elif kind is EventKind.TOOL_START:
            self._tool_started.setdefault(
                (event.turn, event.tool_name), deque()
            ).append(event.ts)
            self._write(event)
        elif kind is EventKind.TOOL_END:
            queue = self._tool_started.get((event.turn, event.tool_name))
            start = queue.popleft() if queue else None
            duration = (event.ts - start) * 1000.0 if start is not None else None
            self._write(event, duration_ms=duration)
        elif kind is EventKind.ERROR:
            self._write(event)
            # 异常收尾保证：run 仍开着且尚未见 RUN_END 时补一条 run_end。
            # 内核在错误路径本会先 ERROR 再 RUN_END（agent.py），此时会有
            # 两条 run_end——消费方取最后一条即可，缺失远比重复有害。
            if self._run_open and not self._run_end_written:
                self._run_end_written = True
                synthetic = AgentEvent(
                    EventKind.RUN_END, turn=event.turn,
                    payload={"stop_reason": "error"}, ts=event.ts,
                )
                self._write(synthetic)
        elif kind is EventKind.RUN_END:
            if not self._run_end_written:
                self._run_end_written = True
            self._run_open = False
            self._write(event)
        return None  # 观察者：永不拦截

    def close(self) -> None:
        """释放文件句柄（进程收尾用；不关也会由 GC 兜底）。"""
        try:
            self._fh.close()
        except OSError:
            pass


def attach_tracing(hooks: HookBus, path: Path | str) -> TraceRecorder:
    """把 TraceRecorder 挂到 *hooks*，事件流写入 *path*（JSONL）。"""
    recorder = TraceRecorder(path)
    for kind in _TRACED_KINDS:
        hooks.on(kind, recorder.handle)
    return recorder


def trace_path_from_env() -> Path | None:
    """RA_TRACE_DIR 开关：未设置返回 None（零开销路径）；设置则给出
    ``<dir>/trace-<时间戳>-<pid>.jsonl``（pid 后缀防同秒并发覆盖）。"""
    raw = os.getenv("RA_TRACE_DIR", "").strip()
    if not raw:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(raw) / f"trace-{stamp}-{os.getpid()}.jsonl"


def maybe_attach_tracing(hooks: HookBus) -> TraceRecorder | None:
    """按 env 开关挂载 tracing：RA_TRACE_DIR 未设置时不产生任何副作用。"""
    path = trace_path_from_env()
    if path is None:
        return None
    return attach_tracing(hooks, path)
