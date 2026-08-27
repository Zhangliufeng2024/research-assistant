"""Tests for the declarative Agent Role / Workflow runtime."""

import asyncio
import json

import pytest

from research_assistant.agent import AgentResult
from research_assistant.workflows import (
    AgentRole,
    WorkflowDefinition,
    WorkflowRegistry,
    WorkflowStep,
    get_workflow_registry,
)


def test_default_registry_exposes_paper_and_generic_workflows():
    registry = get_workflow_registry()
    workflows = {item["id"]: item for item in registry.list_workflows()}
    assert {"paper", "research_sprint", "data_analysis"} <= workflows.keys()
    assert workflows["paper"]["specialized_executor"] == "paper_pipeline"
    assert workflows["research_sprint"]["steps"][1]["depends_on"] == ["scope"]


def test_role_model_routing_is_optional(monkeypatch):
    from research_assistant.workflows import resolve_role_model

    monkeypatch.setenv("RA_MODEL_FAST", "fast-model")
    assert resolve_role_model("base-model", "fast") == "fast-model"
    assert resolve_role_model("base-model", "default") == "base-model"
    monkeypatch.delenv("RA_MODEL_FAST")
    assert resolve_role_model("base-model", "fast") == "base-model"


def test_registry_rejects_unknown_roles_and_cycles():
    registry = WorkflowRegistry()
    registry.register_role(AgentRole("role", "Role", "system"))
    with pytest.raises(ValueError, match="unknown role"):
        registry.register_workflow(WorkflowDefinition(
            "bad-role", "Bad", "", (WorkflowStep("x", "X", "missing"),),
        ))
    with pytest.raises(ValueError, match="dependency cycle"):
        registry.register_workflow(WorkflowDefinition(
            "cycle", "Cycle", "", (
                WorkflowStep("a", "A", "role", ("b",)),
                WorkflowStep("b", "B", "role", ("a",)),
            ),
        ))


def test_generic_workflow_writes_and_restores_node_checkpoints(tmp_path, monkeypatch):
    import research_assistant.workflows.runner as runner

    class FakeClient:
        async def close(self):
            return None

    async def fake_run_agent(**kwargs):
        return AgentResult(text_output=f"done:{kwargs['prompt'].splitlines()[2]}")

    monkeypatch.setattr(runner, "create_llm_client", lambda **kwargs: FakeClient())
    monkeypatch.setattr(runner, "run_agent", fake_run_agent)
    workflow = WorkflowDefinition(
        "mini", "Mini", "", (
            WorkflowStep("a", "A", "planner", prompt="first"),
            WorkflowStep("b", "B", "reviewer", ("a",), prompt="second"),
        ),
    )
    registry = get_workflow_registry()
    workflow.validate(registry.roles)

    async def collect():
        return [frame async for frame in runner.run_registered_workflow(
            workflow, "q", "test-model", tmp_path, tmp_path / "out",
        )]

    first = asyncio.run(collect())
    assert first[-1]["status"] == "success"
    assert (tmp_path / "out" / ".ra" / "workflow" / "a.json").is_file()
    second = asyncio.run(collect())
    assert any(frame["details"]["status"] == "resumed" for frame in second if frame.get("details"))
    assert json.loads((tmp_path / "out" / ".ra" / "workflow" / "b.json").read_text())["status"] == "complete"
