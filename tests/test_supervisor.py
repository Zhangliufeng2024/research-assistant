import asyncio

import pytest

from research_assistant.workflows.supervisor import AgentSupervisor, AgentTaskSpec


@pytest.mark.asyncio
async def test_supervisor_bounds_concurrency_and_emits_lifecycle():
    active = 0
    peak = 0
    events = []

    async def execute(spec):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return spec.id

    results = await AgentSupervisor(max_concurrency=2, event_sink=events.append).run_ready(
        [AgentTaskSpec("a", "literature"), AgentTaskSpec("b", "data"), AgentTaskSpec("c", "figure")],
        execute,
    )
    assert peak == 2
    assert {result.value for result in results} == {"a", "b", "c"}
    assert [event["status"] for event in events if event["agent_id"] == "a"] == ["queued", "running", "complete"]


@pytest.mark.asyncio
async def test_supervisor_isolates_agent_failure_and_honors_cancel():
    async def execute(spec):
        if spec.id == "bad":
            raise RuntimeError("boom")
        return "ok"

    results = await AgentSupervisor(max_concurrency=2).run_ready(
        [AgentTaskSpec("bad", "critic"), AgentTaskSpec("good", "writer")], execute,
    )
    by_id = {result.task_id: result for result in results}
    assert by_id["bad"].status == "failed"
    assert by_id["good"].status == "complete"

    cancel = asyncio.Event()
    cancel.set()
    cancelled = await AgentSupervisor().run_ready([AgentTaskSpec("x", "writer")], execute, cancel_event=cancel)
    assert cancelled[0].status == "cancelled"


@pytest.mark.asyncio
async def test_supervisor_timeout_isolated_to_agent():
    async def execute(spec):
        if spec.id == "slow":
            await asyncio.sleep(0.05)
        return spec.id

    results = await AgentSupervisor(max_concurrency=2).run_ready(
        [AgentTaskSpec("slow", "data", timeout_seconds=0.001), AgentTaskSpec("fast", "review")],
        execute,
    )
    by_id = {item.task_id: item for item in results}
    assert by_id["slow"].status == "failed"
    assert "超时" in by_id["slow"].error
    assert by_id["fast"].status == "complete"


def test_role_policy_exposes_caps_and_allowlist():
    role = __import__("research_assistant.workflows", fromlist=["get_workflow_registry"]).get_workflow_registry().get_role("data_analyst")
    assert role.max_total_tokens
    assert "run_python" in role.tool_allowlist
    assert "run_python" in role.approval_tools


@pytest.mark.asyncio
async def test_tool_allowlist_is_enforced_for_agent_role():
    from research_assistant.tools.registry import ToolRegistry

    registry = ToolRegistry(work_dir=".", allowed_tools=("read_file",))
    assert len(registry.get_schemas()) == 1
    assert registry.get_schemas()[0]["name"] == "read_file"
    denied = await registry.execute("write_file", {"file_path": "x", "content": "no"})
    assert "允许列表" in denied
