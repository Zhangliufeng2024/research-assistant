"""Validated Agent Role and Workflow definitions.

The paper pipeline remains a specialized executor, but its task graph is now
described through the same registry used by generic research workflows.  This
keeps the runtime extensible without allowing arbitrary Python code from a
project file to execute.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentRole:
    """A reusable agent persona and execution policy."""

    id: str
    title: str
    system_prompt: str
    description: str = ""
    max_continuations: int = 8
    model_tier: str = "default"
    max_cost_usd: float | None = None
    max_total_tokens: int | None = None
    max_turns: int | None = None
    tool_allowlist: tuple[str, ...] = field(default_factory=tuple)
    approval_tools: tuple[str, ...] = field(default_factory=tuple)

    def budget_limits(self, global_limits: Any | None = None) -> Any:
        """Return role caps intersected with the workflow's global caps."""
        from ..kernel.budget import BudgetLimits

        global_limits = global_limits or BudgetLimits()

        def minimum(role_value: Any, global_value: Any) -> Any:
            if role_value and global_value:
                return min(role_value, global_value)
            return role_value or global_value

        return BudgetLimits(
            max_cost_usd=minimum(self.max_cost_usd, global_limits.max_cost_usd),
            max_total_tokens=minimum(self.max_total_tokens, global_limits.max_total_tokens),
            max_turns=minimum(self.max_turns, global_limits.max_turns),
            max_wall_seconds=minimum(None, global_limits.max_wall_seconds),
        )


@dataclass(frozen=True)
class WorkflowStep:
    """One node in a workflow DAG."""

    id: str
    title: str
    role: str
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    prompt: str = ""
    timeout_seconds: float | None = None

    def to_task_step(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "depends_on": list(self.depends_on),
            "role": self.role,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class WorkflowDefinition:
    """A safe, declarative multi-agent workflow."""

    id: str
    title: str
    description: str
    steps: tuple[WorkflowStep, ...]
    specialized_executor: str | None = None

    def validate(self, roles: dict[str, AgentRole]) -> None:
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError(f"workflow {self.id!r} has duplicate step ids")
        known = set(ids)
        for step in self.steps:
            if step.role not in roles:
                raise ValueError(f"workflow {self.id!r} references unknown role {step.role!r}")
            unknown = set(step.depends_on) - known
            if unknown:
                raise ValueError(f"workflow {self.id!r} has unknown dependencies: {sorted(unknown)}")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError(f"workflow {self.id!r} contains a dependency cycle")
            if step_id in visited:
                return
            visiting.add(step_id)
            step = next(item for item in self.steps if item.id == step_id)
            for parent in step.depends_on:
                visit(parent)
            visiting.remove(step_id)
            visited.add(step_id)

        for step in self.steps:
            visit(step.id)

    def to_dict(self, roles: dict[str, AgentRole]) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "specialized_executor": self.specialized_executor,
            "steps": [
                {
                    **step.to_task_step(),
                    "role_title": roles[step.role].title,
                    "model_tier": roles[step.role].model_tier,
                    "timeout_seconds": step.timeout_seconds,
                    "tool_allowlist": list(roles[step.role].tool_allowlist),
                    "approval_tools": list(roles[step.role].approval_tools),
                }
                for step in self.steps
            ],
        }


class WorkflowRegistry:
    """In-memory registry with validation at registration time."""

    def __init__(self) -> None:
        self.roles: dict[str, AgentRole] = {}
        self.workflows: dict[str, WorkflowDefinition] = {}

    def register_role(self, role: AgentRole) -> AgentRole:
        if not role.id or role.id.strip() != role.id:
            raise ValueError("role id must be a non-empty stable identifier")
        self.roles[role.id] = role
        # A workflow may have been registered before an optional role plugin;
        # validate all definitions again when a role arrives.
        for workflow in self.workflows.values():
            workflow.validate(self.roles)
        return role

    def register_workflow(self, workflow: WorkflowDefinition) -> WorkflowDefinition:
        if not workflow.id or workflow.id.strip() != workflow.id:
            raise ValueError("workflow id must be a non-empty stable identifier")
        workflow.validate(self.roles)
        self.workflows[workflow.id] = workflow
        return workflow

    def get_role(self, role_id: str) -> AgentRole:
        try:
            return self.roles[role_id]
        except KeyError as exc:
            raise KeyError(f"unknown agent role: {role_id}") from exc

    def get_workflow(self, workflow_id: str) -> WorkflowDefinition:
        try:
            return self.workflows[workflow_id]
        except KeyError as exc:
            raise KeyError(f"unknown workflow: {workflow_id}") from exc

    def list_workflows(self) -> list[dict[str, Any]]:
        return [
            self.workflows[key].to_dict(self.roles)
            for key in sorted(self.workflows)
        ]


def _paper_steps() -> tuple[WorkflowStep, ...]:
    return (
        WorkflowStep("plan", "规划研究", "planner", prompt="规划论文研究问题、章节和证据需求。"),
        WorkflowStep("research", "并行证据研究", "literature_researcher", ("plan",), "围绕研究问题检索并整理可核验证据。"),
        WorkflowStep("figures", "图表与分析", "data_analyst", ("plan",), "设计可复现的数据分析和图表方案。"),
        WorkflowStep("assemble", "组装论文", "scientific_writer", ("research", "figures"), "整合证据和分析，形成完整科研文本。"),
        WorkflowStep("gates", "科研质量门禁", "reviewer", ("assemble",), "检查引用、结构、数据和可复现性问题。"),
        WorkflowStep("finalize", "审阅与定稿", "scientific_writer", ("gates",), "根据门禁结果完成最终审阅和交付。"),
    )


def get_workflow_registry() -> WorkflowRegistry:
    """Build the process-local default registry.

    Definitions are immutable and cheap to construct; callers can copy or
    extend a registry in tests/plugins without mutating global state.
    """
    registry = WorkflowRegistry()
    registry.register_role(AgentRole(
        "planner", "研究规划 Agent", "你是严谨的科研规划专家。", model_tier="fast",
        max_total_tokens=20_000, max_turns=12,
        tool_allowlist=("read_file", "glob_files", "grep_search", "write_file"),
    ))
    registry.register_role(AgentRole(
        "literature_researcher", "证据检索 Agent", "你是文献检索与证据核验专家。", model_tier="fast",
        max_total_tokens=35_000, max_turns=20,
        tool_allowlist=("read_file", "glob_files", "grep_search", "verify_citations", "write_file"),
        approval_tools=("verify_citations",),
    ))
    registry.register_role(AgentRole(
        "data_analyst", "数据分析 Agent", "你是可复现科研分析与图表专家。", model_tier="default",
        max_total_tokens=45_000, max_turns=25,
        tool_allowlist=("read_file", "glob_files", "grep_search", "run_python", "write_file", "edit_file"),
        approval_tools=("run_python",),
    ))
    registry.register_role(AgentRole(
        "scientific_writer", "科研写作 Agent", "你是遵守引用和方法透明原则的科研写作者。", model_tier="strong",
        max_total_tokens=40_000, max_turns=20,
        tool_allowlist=("read_file", "glob_files", "grep_search", "write_file", "edit_file"),
    ))
    registry.register_role(AgentRole(
        "reviewer", "质量审阅 Agent", "你是严格的科研质量和同行评审专家。", model_tier="fast",
        max_total_tokens=25_000, max_turns=12,
        tool_allowlist=("read_file", "glob_files", "grep_search", "verify_citations"),
        approval_tools=("verify_citations",),
    ))
    registry.register_workflow(WorkflowDefinition(
        id="paper",
        title="论文科研流水线",
        description="规划 → 并行证据与图表 → 组装 → 质量门禁 → 定稿。",
        steps=_paper_steps(),
        specialized_executor="paper_pipeline",
    ))
    registry.register_workflow(WorkflowDefinition(
        id="research_sprint",
        title="研究问题冲刺",
        description="用轻量多 Agent 流程快速澄清问题、汇总证据并形成行动方案。",
        steps=(
            WorkflowStep("scope", "问题界定", "planner", prompt="把用户问题拆成可验证的研究子问题和成功标准。"),
            WorkflowStep("evidence", "证据汇总", "literature_researcher", ("scope",), "整理支持或反驳各子问题的证据，并标注检索锚点。"),
            WorkflowStep("action", "研究行动方案", "reviewer", ("evidence",), "评估证据强弱，给出下一步实验、分析或阅读计划。"),
        ),
    ))
    registry.register_workflow(WorkflowDefinition(
        id="data_analysis",
        title="可复现数据分析",
        description="规划分析 → 执行与制图 → 解释结果，产出可复现分析记录。",
        steps=(
            WorkflowStep("analysis_plan", "分析计划", "planner", prompt="制定统计方法、变量定义、质量检查和输出图表清单。"),
            WorkflowStep("analysis_run", "执行分析", "data_analyst", ("analysis_plan",), "读取工作区数据并执行可复现分析，保存脚本和图表。"),
            WorkflowStep("interpretation", "结果解释", "scientific_writer", ("analysis_run",), "解释统计结果、限制和科研含义，避免过度推断。"),
        ),
    ))
    return registry


def resolve_role_model(default_model: str, model_tier: str) -> str:
    """Resolve optional fast/strong routing without breaking one-model setups."""
    tier = str(model_tier or "default").lower()
    if tier not in {"fast", "strong"}:
        return default_model
    configured = os.environ.get(f"RA_MODEL_{tier.upper()}", "").strip()
    return configured or default_model
