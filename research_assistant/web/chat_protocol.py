"""会话协议纯函数层（工程债拆分，2026-08-31）。

从 ``web/chat.py`` 抽出：附件校验/落盘、产物路径提取、slash 命令解析、
Plan 门指令、系统指令拼接、_HistoryClient 与出站信箱背压。全部为无 FastAPI
依赖的纯逻辑；聊天运行时与 REST CRUD 仍在 chat.py，经本模块共享函数。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core import (
    execution_contract_addendum,
    load_system_instructions,
    safe_resolve,
)
from ..kernel.budget import BudgetGuard
from ..llm.base import LLMClient, LLMResponse, OnChunkCallback
from ..tools.file_ops import _reject_windows_hazard
from .chat_state import _guess_image_mime, _outputs_root

MAX_USER_LENGTH = 8_000
MAX_STEER_LENGTH = 2_000
PREVIEW_LIMIT = 400
ARTIFACT_PATH_LIMIT = 8
ATTACHMENTS_MAX = 8
UPLOAD_TOTAL_LIMIT = 50 * 1024 * 1024
_UPLOAD_NAME_RE = re.compile(r"[^A-Za-z0-9\u4e00-\u9fff._ ()\[\]-]+")
VISION_IMAGE_MAX_BYTES = 5 * 1024 * 1024
VISION_MAX_IMAGES = 5
_IMAGE_MIME_ALLOW = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_ARTIFACT_RE = re.compile(
    r"[^\s\"'`<>()\[\]{};,]+\.(?:png|jpe?g|gif|svg|webp|pdf|docx|doc|csv|xlsx?"
    r"|md|bib|tex|json|html?)",
    re.IGNORECASE,
)
COMMAND_HELP_TEXT = """可用命令：
  /budget  设置本会话预算上限（覆盖 RA_MAX_* 环境配置）
    用法：/budget cost=<美元> tokens=<N> turns=<N> wall_seconds=<秒>
  /model   临时切换本会话后续回合使用的模型
    用法：/model <模型名>
  /role    为下一回合指定角色设定（注入系统上下文）
    用法：/role <角色名>
  /skill   为下一回合注入一个技能指南作为上下文
    用法：/skill <技能名>
  /plan    先出计划，等你确认后再执行
    用法：/plan <请求内容>
  /help    显示本帮助"""
_BUDGET_FIELD_MAP: dict[str, tuple[str, type]] = {
    "cost": ("max_cost_usd", float),
    "tokens": ("max_total_tokens", int),
    "turns": ("max_turns", int),
    "wall_seconds": ("max_wall_seconds", float),
}


def _vision_enabled() -> bool:
    """视觉开关：RA_VISION_DISABLED=1 时会话层拒绝一切图片输入。"""
    return os.getenv("RA_VISION_DISABLED", "0") != "1"


def bounded_put(queue: asyncio.Queue, frame: dict) -> bool:
    """入队一帧；队列满时**丢最旧**再入，返回是否发生过丢弃。

    A+ 阶段 1 / C-7 的背压策略核心，独立成模块级函数以便直接测试
    （内联在 ws_chat 的闭包里只能靠构造慢客户端来覆盖，不可靠）。

    为什么丢最旧而不是丢最新：帧流是**有序增量**，丢最新会截断尾部（丢掉
    result/usage 终态帧）、丢中间会造成空洞；丢最旧只是让本连接的直播流
    暂时落后，完整序列仍在回合句柄的环形缓冲里，重连 ``attach{after}``
    可以精确补回。

    刻意**不修改 frame**：入队对象可能与环形缓冲里的帧共享引用（attach
    回放的整段无 await 快照），就地改写会污染回放源。

    Args:
        queue: 目标队列。``maxsize<=0``（无界）时退化为 ``put_nowait``。
        frame: 待入队帧，原样放入。

    Returns:
        True 表示发生了丢弃（调用方据此记数/告警）。
    """
    try:
        queue.put_nowait(frame)
        return False
    except asyncio.QueueFull:
        pass  # 控制流：队列满即丢弃最旧帧腾位，返回值由调用方记数
    try:
        queue.get_nowait()
    except asyncio.QueueEmpty:  # pragma: no cover — 竞态窗口极窄
        return False
    try:
        queue.put_nowait(frame)
    except asyncio.QueueFull:  # pragma: no cover — 上一步刚腾出位
        return False
    return True


def _outbox_maxsize() -> int:
    raw = os.getenv("RA_CHAT_OUTBOX_MAXSIZE")
    try:
        value = int(raw) if raw is not None else 1000
    except (TypeError, ValueError):
        value = 1000
    return value if value > 0 else 0


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


def _jsonable_arguments(args: dict | None) -> dict:
    """工具卡 arguments 保证可 JSON 序列化（不可序列化时降级为 repr 文本）。"""
    if not isinstance(args, dict):
        return {}
    try:
        json.dumps(args)
        return args
    except (TypeError, ValueError):
        return {"repr": repr(args)[:400]}


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


def _split_slash(text: str) -> tuple[str, str]:
    """/name rest... → (name, rest)；"/plan 做X" → ("plan", "做X")。"""
    head = text[1:].split(None, 1)
    name = head[0].lower() if head else ""
    rest = head[1].strip() if len(head) > 1 else ""
    return name, rest


def _apply_budget_override(budget: BudgetGuard, rest: str) -> str:
    """把 ``/budget key=value …`` 覆盖写进会话级 BudgetGuard。

    返回空串表示成功；否则返回中文错误串（调用方转 error 帧）。覆盖是
    会话级持久的——写进共享 guard 的 limits，后续每一回合都生效，直到
    下次 /budget 再次覆盖（不给「回滚」语义：重连/重启即回环境默认）。
    """
    pairs: dict[str, float] = {}
    for token in rest.split():
        key, eq, raw = token.partition("=")
        if not eq:
            return f"预算参数必须写成 key=value：{token}"
        if key not in _BUDGET_FIELD_MAP:
            return f"未知预算键: {key}（可用：cost / tokens / turns / wall_seconds）"
        try:
            num = float(raw)
        except ValueError:
            return f"budget {key}= 必须是正数"
        if num <= 0:
            return f"budget {key}= 必须是正数"
        pairs[key] = num
    if not pairs:
        return ("用法：/budget cost=<美元> tokens=<N> turns=<N> wall_seconds=<秒>"
                "（至少一项）")
    for key, num in pairs.items():
        field, typ = _BUDGET_FIELD_MAP[key]
        setattr(budget.limits, field, int(num) if typ is int else float(num))
    return ""


def _budget_limits_summary(budget: BudgetGuard) -> str:
    """/budget 成功后的确认文案：回显当前全部生效上限。"""
    lim = budget.limits
    parts: list[str] = []
    if lim.max_cost_usd:
        parts.append(f"cost=${lim.max_cost_usd:g}")
    if lim.max_total_tokens:
        parts.append(f"tokens={lim.max_total_tokens}")
    if lim.max_turns:
        parts.append(f"turns={lim.max_turns}")
    if lim.max_wall_seconds:
        parts.append(f"wall_seconds={lim.max_wall_seconds:g}")
    return "本会话预算上限已更新：" + (
        "；".join(parts) if parts else "当前无生效上限（不限制）"
    )


def _planner_instructions(base: str) -> str:
    """Plan 门 planner 回合的系统提示：只出计划，不执行、不用工具。"""
    return base + """

## 计划模式（Plan Gate——只读规划阶段）

用户要求先看到计划、确认后再执行。当前你处于只读规划阶段：
- 不能调用任何工具，也不会真正执行任务；不要假装已经执行。
- 输出一份简明、可执行的中文计划：
  1. 目标一句话确认（如有歧义，列出你的理解与假设）；
  2. 步骤清单：每步一句话，说明做什么、产出什么文件或结论；
  3. 需要的数据 / 文件 / 关键参数（未知处注明假设）；
  4. 风险与替代方案（如有）。
- 结尾固定加一行：「——请确认：同意后我将按此计划执行；也可直接提出修改意见。」
"""


class _PlannerTools:
    """Plan 门 planner 回合的空工具面：不向模型暴露任何工具。

    内核只触达 ``get_schemas()`` 与 ``execute()``；schemas 为空时模型无
    工具可调，execute 兜底拒绝（防御性——正常不会触达）。
    """

    def get_schemas(self) -> list[dict]:
        return []

    async def execute(self, name: str, arguments: dict) -> str:
        return "Error: 计划阶段不可用工具（只读规划）"


def _safe_upload_name(raw: str) -> str:
    """把客户端文件名消毒成可直接落盘的安全名。

    取 basename（剥掉目录成分与盘符）、剔除非法字符（冒号随之消失，ADS
    形态无从构造）、Windows 保留设备名加下划线前缀降级、限长保扩展名。
    """
    name = Path(str(raw).replace("\\", "/")).name
    name = _UPLOAD_NAME_RE.sub("_", name).strip(" ._") or "file.bin"
    if _reject_windows_hazard(name):
        name = "_" + name  # CON/NUL 等：降级而非拒绝，用户视角更顺
    dot = name.rfind(".")
    if len(name) > 120:
        if dot > 0:
            name = name[: 120 - (len(name) - dot)] + name[dot:]
        else:
            name = name[:120]
    return name or "file.bin"


def _image_parts_from_entry(entry: dict) -> list[dict]:
    """从历史条目的 attachments 提取图片 → 统一内部表示的 image 部件。

    纯函数口径（可不经 WS 直接测）：读 attachments 里 mime 为图片的文件、
    base64 编码；文件缺失 / 超过单图上限 / 非白名单 mime 的条目静默跳过
    （留档的路径清单文本仍在，模型至少知道附件存在）。
    """
    parts: list[dict] = []
    atts = entry.get("attachments")
    if not isinstance(atts, list):
        return parts
    for a in atts:
        if not isinstance(a, dict):
            continue
        path = str(a.get("path") or "")
        if not path:
            continue
        mime = str(a.get("mime_type") or "") or _guess_image_mime(path)
        if not mime or mime not in _IMAGE_MIME_ALLOW:
            continue
        try:
            data = Path(path).read_bytes()
        except OSError:
            continue  # 文件已清理/不可读：降级为无图片，不阻塞回合
        if len(data) > VISION_IMAGE_MAX_BYTES:
            continue
        parts.append({
            "type": "image",
            "media_type": mime,
            "data": base64.b64encode(data).decode("ascii"),
        })
    return parts


def _prepare_attachments(cwd: Path, sid: str, raw: Any) -> tuple[list[dict], str]:
    """WS user 消息附件总入口：路径引用 + 内联 base64 图片统一校验。

    返回 (规范化的附件元数据列表, 错误串)；出错时元数据为空列表、错误串
    非空（调用方转成 error 帧，不开轮）。错误串口径与
    _validate_attachment_refs 保持一致的中文风格。
    """
    if raw is None:
        return [], ""
    if not isinstance(raw, list):
        return [], "attachments 必须是数组"
    if len(raw) > ATTACHMENTS_MAX:
        return [], f"附件数量超过上限（{ATTACHMENTS_MAX} 个）"

    inline: list[dict] = []
    refs: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            return [], "attachments 元素必须是对象"
        if item.get("data_base64"):
            inline.append(item)
        elif item.get("path"):
            refs.append(item)
        else:
            return [], "附件缺少 path 或 data_base64"

    meta: list[dict] = []
    if refs:
        checked = _validate_attachment_refs(cwd, sid, refs)
        if isinstance(checked, str):
            return [], checked
        # 图片类路径引用补 mime_type：与内联图片同一套视觉注入口径
        meta.extend(
            {**a, "mime_type": mime} if (mime := _guess_image_mime(a["name"] or a["path"])) else a
            for a in checked
        )

    if inline:
        if not _vision_enabled():
            return [], "当前配置已禁用视觉输入（RA_VISION_DISABLED=1），无法接收图片附件"
        # 图片总数（路径引用中的图片 + 内联图片）单条消息 ≤ VISION_MAX_IMAGES
        ref_images = [a for a in meta if _guess_image_mime(str(a.get("name", "")))]
        if len(inline) + len(ref_images) > VISION_MAX_IMAGES:
            return [], f"图片数量超过上限（每条消息最多 {VISION_MAX_IMAGES} 张）"
        for item in inline:
            mime = str(item.get("mime_type") or "") or _guess_image_mime(
                str(item.get("name") or "")
            ) or ""
            if mime not in _IMAGE_MIME_ALLOW:
                return [], (
                    f"不支持的图片类型：{mime or '未知'}"
                    f"（仅支持 {', '.join(sorted(_IMAGE_MIME_ALLOW))}）"
                )
            try:
                data = base64.b64decode(str(item["data_base64"]), validate=True)
            except (ValueError, TypeError):
                return [], f"附件 {item.get('name', '')} 的 base64 数据无法解码"
            if len(data) > VISION_IMAGE_MAX_BYTES:
                limit_mb = VISION_IMAGE_MAX_BYTES // (1024 * 1024)
                return [], f"图片 {item.get('name', '')} 超过大小上限（{limit_mb}MB）"
            meta.append(_save_inline_image(
                cwd, sid, str(item.get("name") or ""), mime, data,
            ))
    return meta, ""


def _validate_attachment_refs(cwd: Path, sid: str, raw: Any) -> list[dict] | str:
    """校验 user 动作携带的 attachments 引用：必须指向本会话 uploads 目录。

    返回规范化的 [{"name","path"}]；不合法时返回中文错误串（调用方转成
    error 帧）。围栏用 safe_resolve——即便是绝对路径也必须落在
    outputs/<sid>/uploads 内，杜绝跨会话/跨目录引用。
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        return "attachments 必须是数组"
    if len(raw) > ATTACHMENTS_MAX:
        return f"附件数量超过上限（{ATTACHMENTS_MAX} 个）"
    uploads_root = _outputs_root(cwd) / sid / "uploads"
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            return "attachments 元素必须是对象"
        path = str(item.get("path") or "").strip()
        if not path:
            return "附件缺少 path"
        try:
            resolved = safe_resolve(Path(path), uploads_root)
        except ValueError:
            return f"附件路径越界（仅允许本会话 uploads 目录内的文件）：{path}"
        out.append({
            "name": str(item.get("name") or resolved.name)[:120],
            "path": str(resolved),
        })
    return out


def _save_inline_image(cwd: Path, sid: str, name: str, mime: str, data: bytes) -> dict:
    """内联图片落盘 outputs/<sid>/uploads/ 留档，返回历史附件元数据。"""
    stamp = datetime.now().strftime("%H%M%S_%f")
    safe_name = _safe_upload_name(name or f"image.{mime.split('/', 1)[-1]}")
    dest = _outputs_root(cwd) / sid / "uploads"
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"{stamp}_{safe_name}"
    target.write_bytes(data)
    return {"name": safe_name, "path": str(target), "mime_type": mime}


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


def _content_for_llm(entry: dict) -> dict:
    """把历史条目展平为内核可见的 {role, content}：附件以路径清单并入正文。

    history.json 存结构化 attachments 字段供 UI 渲染；模型侧只需要知道
    「文件在哪、怎么读」，因此在喂给内核前（且仅在此处）拼进文本——权威
    数据保持结构化，不因模型的展示口径而失真。

    多模态（G-3）：条目携带图片附件时，content 升级为**多部件列表**
    （统一内部表示：text + image 部件；图片数据从留盘文件现读现编码），
    由各 LLM 客户端的消息构造层适配为对应协议的分格式。
    """
    flat = {"role": entry.get("role", "user"), "content": str(entry.get("content", ""))}
    atts = entry.get("attachments")
    if isinstance(atts, list) and atts:
        lines = "\n".join(
            f'- {a.get("name", "")}: {a.get("path", "")}（可用 read_file/grep 直接读取）'
            for a in atts
            if isinstance(a, dict) and a.get("path") and not a.get("mime_type")
        )
        if lines:
            flat["content"] = (
                f'{flat["content"]}\n\n[本条消息携带的附件]\n{lines}'
            )
        image_parts = _image_parts_from_entry(entry)
        if image_parts:
            flat["content"] = [
                {"type": "text", "text": flat["content"]},
                *image_parts,
            ]
    return flat


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
        on_thought: OnChunkCallback | None = None,
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
            on_thought=on_thought,
        )

    async def close(self) -> None:
        await self._inner.close()


OUTBOX_MAXSIZE = _outbox_maxsize()
