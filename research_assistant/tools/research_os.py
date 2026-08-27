"""研究台账（Research OS）写入工具。

背景：平台库 PlatformStore 的 create_claim / create_evidence / create_research_item /
create_decision 此前只有 web/routes.py 的 REST 路由在调（前端手动填表），agent 的
工具面没有任何写入口——导致 ProjectHome 的综合写作门禁（ready_for_synthesis 要求
每条 claim 至少有一条 supports 证据）对不手动填表的用户永远不满足。

库与项目的定位完全复刻 web/app.py lifespan 的初始化约定：
  <workspace>/.ra/platform.sqlite3 + store.ensure_project(workspace)
这样 CLI / 会话场景经本工具写入的记录与 REST 场景落在同一份台账上
（ensure_project 按 resolve 后的 root 匹配，天然幂等）。

实现约定：
- 全部 sqlite 调用经 asyncio.to_thread 下放线程，避免阻塞事件循环；
- 任何失败都返回以 "Error: " 开头的中文错误串而不是抛异常——工具结果直接进
  模型上下文，抛出去只会变成笼统的 "Error executing ..."，模型无从自救；
- 成功返回必须携带新记录的 id，供后续 link 引用。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # 仅类型标注用；运行时禁止模块级导入——见 _open_ledger_sync 内的说明
    from ..runtime.platform_store import PlatformStore

_ITEM_KINDS = ("question", "hypothesis", "objective", "note")

# 台账概览里单行文本的最大展示长度，控制工具结果体积（结果会进模型上下文）
_PREVIEW_LIMIT = 80


def _preview(text: Any, limit: int = _PREVIEW_LIMIT) -> str:
    """压缩成单行摘要，超长截断——台账列表只用于模型自查 id，不必全量回显。"""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _workspace_root(workspace: str | None) -> Path:
    return Path(workspace or ".").resolve()


def _open_ledger_sync(workspace: str | None) -> tuple[PlatformStore, str]:
    """按 web/app.py 的约定从磁盘定位平台库并解析默认项目 id。

    注意：库文件不存在时直接抛 FileNotFoundError——绝不能用 PlatformStore
    构造函数隐式建库（它会连目录一起创建），否则"未初始化工作区"会被静默
    变成一份空台账，用户在 Project Home 看到两套对不上的数据。
    """
    # 函数级延迟导入：本模块被 tools.registry 在模块级导入，而 runtime 包的
    # __init__ 会经 scheduler_dispatcher 反向依赖 research_assistant.api
    # （api → agent → tools.registry），模块级导入会形成循环。platform_store
    # 模块本身只依赖标准库，导入后由 sys.modules 缓存，无重复开销。
    from ..runtime.platform_store import PlatformStore

    root = _workspace_root(workspace)
    db_path = root / ".ra" / "platform.sqlite3"
    if not db_path.is_file():
        raise FileNotFoundError(str(db_path))
    # _initialize 全部 CREATE TABLE IF NOT EXISTS，重复打开幂等安全
    store = PlatformStore(db_path)
    project = store.ensure_project(root)
    return store, str(project["id"])


async def _ledger_op(
    op_desc: str,
    workspace: str | None,
    fn: Callable[[PlatformStore, str], Any],
) -> Any:
    """统一封装：开库 → 执行 fn(store, project_id) → 把异常翻译成中文错误串。"""
    try:
        return await asyncio.to_thread(_run_with_store, workspace, fn)
    except FileNotFoundError as exc:
        return (
            f"Error: 研究台账不可用：未找到科研对象库 {exc}。"
            "当前工作区尚未初始化（Web 应用启动时会自动创建 .ra/platform.sqlite3）；"
            "请跳过台账记录继续任务，或提示用户先通过 Web 界面打开本项目。"
        )
    except LookupError as exc:
        # record_research_evidence 里用于表达"claim_id 无效"的专用通道
        return (
            f"Error: {op_desc}失败：目标记录不存在或不属于当前项目"
            f"（id={exc}）。请先调用 list_research_ledger 查询有效 id 后重试，"
            "不要凭记忆猜测 id。"
        )
    except ValueError as exc:
        return f"Error: {op_desc}失败：{exc}"
    except Exception as exc:  # 兜底：sqlite 锁冲突、磁盘故障等一律友好返回
        return f"Error: {op_desc}失败：{type(exc).__name__}: {exc}"


def _run_with_store(
    workspace: str | None,
    fn: Callable[[PlatformStore, str], Any],
) -> Any:
    store, project_id = _open_ledger_sync(workspace)
    return fn(store, project_id)


async def record_research_claim(
    statement: str,
    status: str = "proposed",
    confidence: float | None = None,
    *,
    workspace: str | None = None,
) -> str:
    """把一条可核查的科学论断写入研究台账，返回携带 claim_id 的确认串。"""
    text = " ".join(str(statement or "").split())
    if not text:
        return "Error: statement 不能为空——请给出要记录的科学论断原文。"
    conf: float | None = None
    if confidence is not None:
        try:
            conf = float(confidence)
        except (TypeError, ValueError):
            return "Error: confidence 必须是 0 到 1 之间的数字。"
        if not 0 <= conf <= 1:
            return "Error: confidence 必须介于 0 与 1 之间（例如 0.8）。"

    def _op(store: PlatformStore, project_id: str) -> tuple[str, str]:
        claim = store.create_claim(
            project_id=project_id, text=text,
            status=str(status or "proposed"), confidence=conf,
        )
        return str(claim["id"]), str(claim.get("status") or status)

    result = await _ledger_op("记录主张", workspace, _op)
    if isinstance(result, str):  # 错误串原样透传
        return result
    claim_id, final_status = result
    return (
        f"已记录研究主张 claim_id={claim_id}（状态 {final_status}）。"
        f"后续挂证据时引用该 id；每条主张至少挂一条 supports 证据才能满足综合写作门禁。"
    )


async def record_research_evidence(
    claim_id: str,
    source_title: str,
    source_url: str = "",
    note: str = "",
    *,
    workspace: str | None = None,
) -> str:
    """为目标主张挂一条证据并自动建立 supports 链接。"""
    cid = str(claim_id or "").strip()
    title = " ".join(str(source_title or "").split())
    if not cid:
        return "Error: claim_id 不能为空——先用 list_research_ledger 查询要挂证据的主张 id。"
    if not title:
        return "Error: source_title 不能为空——请给出证据出处名称（论文标题、报告名等）。"

    def _op(store: PlatformStore, project_id: str) -> tuple[str, str]:
        # 先只读校验 claim 归属，避免坏 id 时先落一条孤儿证据再链接失败留下脏数据
        claims = store.list_claims(project_id, limit=1000)
        if not any(str(c.get("id")) == cid for c in claims):
            raise LookupError(cid)
        # 证据矩阵单元格展示 source_anchor + excerpt，所以出处名称放 anchor、
        # 说明放 excerpt；URL 进 metadata 以便审计追溯
        evidence = store.create_evidence(
            project_id=project_id,
            source_anchor=title,
            excerpt=_preview(note, 500),
            kind="source",
            metadata={
                "source_url": str(source_url or "").strip(),
                "source_title": title,
                "origin": "agent",
            },
        )
        store.link_evidence(project_id=project_id, claim_id=cid, evidence_id=str(evidence["id"]))
        return str(evidence["id"]), cid

    result = await _ledger_op("挂证据", workspace, _op)
    if isinstance(result, str):
        return result
    evidence_id, target = result
    return (
        f"已为主张 {target} 挂上证据 evidence_id={evidence_id}（relation=supports）。"
        "该记录已进入 Project Home 证据矩阵。"
    )


async def record_research_item(
    title: str,
    kind: str = "question",
    notes: str = "",
    *,
    workspace: str | None = None,
) -> str:
    """登记一个研究对象条目（研究问题 / 假设 / 目标 / 备注）。"""
    clean_title = " ".join(str(title or "").split())
    if not clean_title:
        return "Error: title 不能为空——请给出研究对象条目的标题。"
    clean_kind = str(kind or "question").strip()
    if clean_kind not in _ITEM_KINDS:
        joined = "/".join(_ITEM_KINDS)
        return f"Error: kind 仅支持 {joined}，收到：{clean_kind}。"

    def _op(store: PlatformStore, project_id: str) -> tuple[str, str]:
        # 返回元组而非裸 str：_ledger_op 用 "Error: " 字符串承载错误，
        # 成功载荷若是裸 str 会与之无法区分（见下方 isinstance 判断）
        item = store.create_research_item(
            project_id=project_id, kind=clean_kind,
            title=clean_title, body=str(notes or ""),
        )
        return str(item["id"]), clean_kind

    result = await _ledger_op("登记研究对象", workspace, _op)
    if isinstance(result, str):
        return result
    item_id, final_kind = result
    return f"已登记研究对象 item_id={item_id}（kind={final_kind}）：{_preview(clean_title, 60)}"


async def record_research_decision(
    title: str,
    rationale: str = "",
    status: str = "active",
    *,
    workspace: str | None = None,
) -> str:
    """把一个关键研究取舍（方法选型、口径确定、范围裁剪等）落账为决策记录。"""
    clean_title = " ".join(str(title or "").split())
    if not clean_title:
        return "Error: title 不能为空——请概括这次决策做了什么决定。"

    def _op(store: PlatformStore, project_id: str) -> tuple[str, str]:
        decision = store.create_decision(
            project_id=project_id, title=clean_title,
            rationale=str(rationale or ""), status=str(status or "active"),
        )
        return str(decision["id"]), str(decision.get("status") or status)

    result = await _ledger_op("落账决策", workspace, _op)
    if isinstance(result, str):
        return result
    decision_id, final_status = result
    return f"已落账决策 decision_id={decision_id}（status={final_status}）：{_preview(clean_title, 60)}"


async def list_research_ledger(*, workspace: str | None = None) -> str:
    """列出台账现有 item / claim / evidence / decision 概览，便于模型自查 id。"""

    def _op(store: PlatformStore, project_id: str) -> dict[str, Any]:
        return {
            "items": store.list_research_items(project_id, limit=200),
            "claims": store.list_claims(project_id, limit=200),
            "decisions": store.list_decisions(project_id, limit=200),
            "evidence": store.list_evidence(project_id, limit=500),
            "quality": store.research_quality_report(project_id),
        }

    result = await _ledger_op("读取台账", workspace, _op)
    if isinstance(result, str):
        return result

    items = result["items"]
    claims = result["claims"]
    decisions = result["decisions"]
    quality = result["quality"]
    if not items and not claims and not decisions:
        return (
            "研究台账为空：尚无 item / claim / decision 记录。"
            "可用 record_research_claim / record_research_item 开始落账。"
        )

    lines = [
        f"研究台账概览（items={len(items)}, claims={len(claims)}, "
        f"evidence={len(result['evidence'])}, decisions={len(decisions)}）",
    ]
    if items:
        lines.append("[研究对象]")
        lines.extend(
            f"- item_id={row.get('id')} [{row.get('kind')}] {_preview(row.get('title'))}"
            for row in items
        )
    if claims:
        lines.append("[主张]（括号内为已挂证据数）")
        for row in claims:
            links = row.get("evidence_links") or []
            summary = f"- claim_id={row.get('id')} [{row.get('status')}] {_preview(row.get('text'))}"
            lines.append(f"{summary}（证据 {len(links)} 条）")
    if decisions:
        lines.append("[决策]")
        lines.extend(
            f"- decision_id={row.get('id')} [{row.get('status')}] {_preview(row.get('title'))}"
            for row in decisions
        )
    synthesis_ready = bool(quality.get("ready_for_synthesis"))
    uncovered = int(quality.get("claims", {}).get("uncovered") or 0)
    lines.append(
        f"门禁状态：ready_for_synthesis={'是' if synthesis_ready else '否'}"
        f"（无证据支撑的主张 {uncovered} 条；挂满 supports 证据后即可满足综合写作门禁）"
    )
    lines.append("引用以上任何 id 前，以其在本列表中的最新取值为准。")
    return "\n".join(lines)
