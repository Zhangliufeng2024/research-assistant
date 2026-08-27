"""A1 研究台账 agent 工具的契约测试。

覆盖四条主链路：
1. record → list 往返（经 ToolRegistry.execute，验证 workspace 注入接线）；
2. evidence 正确挂到 claim 并点亮综合写作门禁（ready_for_synthesis）；
3. 坏 claim_id 得到友好错误且不留孤儿证据；
4. 无平台库的工作区得到友好错误且不隐式建库。
"""

from __future__ import annotations

import re
from pathlib import Path

from research_assistant.runtime import PlatformStore
from research_assistant.tools.registry import TOOL_DEFINITIONS, ToolRegistry
from research_assistant.tools.research_os import (
    list_research_ledger,
    record_research_claim,
    record_research_evidence,
)

_LEDGER_TOOL_NAMES = {
    "record_research_claim",
    "record_research_evidence",
    "record_research_item",
    "record_research_decision",
    "list_research_ledger",
}


def _make_workspace(tmp_path: Path) -> tuple[Path, PlatformStore, str]:
    """参照 tests/test_research_store.py 的构造方式建临时库。

    与 web/app.py lifespan 一致：先建 <ws>/.ra/platform.sqlite3，
    再 ensure_project(ws)——agent 工具从磁盘推导时命中的就是这行项目记录。
    """
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    return tmp_path, store, project["id"]


def _extract_id(text: str, kind: str) -> str:
    match = re.search(rf"{kind}=([0-9a-f]+)", text)
    assert match is not None, f"返回串缺少 {kind}：{text}"
    return match.group(1)


async def test_ledger_tools_registered_and_roundtrip(tmp_path):
    ws, _store, _pid = _make_workspace(tmp_path)
    schema_names = {td["name"] for td in TOOL_DEFINITIONS}
    assert _LEDGER_TOOL_NAMES <= schema_names

    registry = ToolRegistry(work_dir=str(ws))
    claim_res = await registry.execute(
        "record_research_claim",
        {"statement": "掺量 5% 的钢纤维使试件抗折强度提升约 20%", "confidence": 0.8},
    )
    assert not claim_res.startswith("Error"), claim_res
    claim_id = _extract_id(claim_res, "claim_id")

    item_res = await registry.execute(
        "record_research_item", {"title": "长期收缩行为待验证", "kind": "question"},
    )
    assert not item_res.startswith("Error"), item_res
    item_id = _extract_id(item_res, "item_id")

    decision_res = await registry.execute(
        "record_research_decision",
        {"title": "采用 RILEM 推荐加载制度", "rationale": "与既有数据可比"},
    )
    assert not decision_res.startswith("Error"), decision_res
    decision_id = _extract_id(decision_res, "decision_id")

    listing = await registry.execute("list_research_ledger", {})
    for record_id in (claim_id, item_id, decision_id):
        assert record_id in listing
    assert "门禁状态" in listing


async def test_evidence_attaches_to_claim_and_satisfies_gate(tmp_path):
    ws, store, pid = _make_workspace(tmp_path)
    registry = ToolRegistry(work_dir=str(ws))

    claim_res = await registry.execute(
        "record_research_claim", {"statement": "基准配合比 28d 强度满足 C50"},
    )
    claim_id = _extract_id(claim_res, "claim_id")
    # 挂证据前门禁必须不满足——这正是本工具要打通的场景
    assert store.research_quality_report(pid)["ready_for_synthesis"] is False

    evidence_res = await registry.execute(
        "record_research_evidence",
        {
            "claim_id": claim_id,
            "source_title": "ACI Materials Journal, 2021",
            "source_url": "https://doi.org/10.14359/test",
            "note": "表 4 报告 28d 抗压强度均值 55.2 MPa",
        },
    )
    assert not evidence_res.startswith("Error"), evidence_res
    evidence_id = _extract_id(evidence_res, "evidence_id")

    claims = store.list_claims(pid)
    assert len(claims) == 1
    links = claims[0]["evidence_links"]
    assert len(links) == 1
    assert links[0]["evidence_id"] == evidence_id
    assert links[0]["relation"] == "supports"
    # source_title 落在 anchor（证据矩阵单元格展示字段）、URL 落 metadata
    evidences = store.list_evidence(pid)
    assert len(evidences) == 1
    assert evidences[0]["source_anchor"] == "ACI Materials Journal, 2021"
    assert evidences[0]["metadata"]["source_url"].endswith("/test")
    assert evidences[0]["metadata"]["origin"] == "agent"
    # 挂上 supports 证据后综合写作门禁点亮
    report = store.research_quality_report(pid)
    assert report["claims"]["uncovered"] == 0
    assert report["ready_for_synthesis"] is True


async def test_bad_claim_id_returns_friendly_error_without_orphan(tmp_path):
    ws, store, pid = _make_workspace(tmp_path)
    registry = ToolRegistry(work_dir=str(ws))

    result = await registry.execute(
        "record_research_evidence",
        {"claim_id": "deadbeef" * 4, "source_title": "不存在的出处"},
    )
    assert result.startswith("Error")
    assert "不存在" in result
    assert "list_research_ledger" in result
    # 关键反副作用断言：坏 id 不允许先落一条孤儿证据再链接失败
    assert store.list_evidence(pid) == []
    assert store.list_claims(pid) == []


async def test_missing_db_returns_friendly_error_and_creates_nothing(tmp_path):
    empty_ws = tmp_path / "blank"
    empty_ws.mkdir()
    registry = ToolRegistry(work_dir=str(empty_ws))

    claim_result = await registry.execute(
        "record_research_claim", {"statement": "无库工作区的论断"},
    )
    assert claim_result.startswith("Error")
    assert "不可用" in claim_result
    listing = await registry.execute("list_research_ledger", {})
    assert listing.startswith("Error")
    assert "不可用" in listing
    evidence_result = await registry.execute(
        "record_research_evidence",
        {"claim_id": "whatever", "source_title": "x"},
    )
    assert evidence_result.startswith("Error")
    # 绝不允许隐式建库：否则未初始化工作区会被静默变成一份空台账
    assert not (empty_ws / ".ra").exists()


async def test_direct_function_call_with_workspace_kwarg(tmp_path):
    """不经 ToolRegistry 直接调函数（workspace 显式传参）也应可用。"""
    ws, store, pid = _make_workspace(tmp_path)
    claim_res = await record_research_claim("模型 A 收敛快于基线", workspace=str(ws))
    assert not claim_res.startswith("Error"), claim_res
    claim_id = _extract_id(claim_res, "claim_id")
    link_res = await record_research_evidence(
        claim_id, "NeurIPS 2020 论文", note="Table 2", workspace=str(ws),
    )
    assert not link_res.startswith("Error"), link_res
    assert store.list_claims(pid)[0]["evidence_links"]

    listing = await list_research_ledger(workspace=str(ws))
    assert claim_id in listing


async def test_invalid_inputs_get_friendly_errors(tmp_path):
    ws, _store, _pid = _make_workspace(tmp_path)
    registry = ToolRegistry(work_dir=str(ws))

    bad_confidence = await registry.execute(
        "record_research_claim", {"statement": "x", "confidence": 7},
    )
    assert bad_confidence.startswith("Error")
    assert "0" in bad_confidence and "1" in bad_confidence

    empty_statement = await registry.execute("record_research_claim", {"statement": "   "})
    assert empty_statement.startswith("Error")
    assert "statement" in empty_statement

    bad_kind = await registry.execute(
        "record_research_item", {"title": "t", "kind": "rumor"},
    )
    assert bad_kind.startswith("Error")
    assert "kind" in bad_kind

    missing_source = await registry.execute(
        "record_research_evidence", {"claim_id": "abc", "source_title": ""},
    )
    assert missing_source.startswith("Error")
    assert "source_title" in missing_source
