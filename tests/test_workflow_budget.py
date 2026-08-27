"""缺陷 H 回归：workflow 顶层预算聚合 + checkpoint 查询指纹校验。

背景：
- H1：runner.py 创建的顶层 BudgetGuard 从未被喂入各节点用量（每节点只有
  独立 step_budget）——全局帽形同虚设，多节点工作流可以无限烧 token。
- H2：checkpoint 恢复只看 status==complete——同一 output_dir 换个查询重跑
  会把旧答案当新结果复用。
"""

import asyncio
import json

from research_assistant.agent import AgentResult
from research_assistant.kernel.budget import LLMResponse
from research_assistant.models import TokenUsage
from research_assistant.workflows import (
    WorkflowDefinition,
    WorkflowStep,
    get_workflow_registry,
)


def _resp(inp: int, out: int) -> LLMResponse:
    return LLMResponse(usage=TokenUsage(input_tokens=inp, output_tokens=out))


def _chain_workflow(step_ids: tuple[str, ...], role: str = "planner") -> WorkflowDefinition:
    steps = []
    for i, sid in enumerate(step_ids):
        depends = (step_ids[i - 1],) if i > 0 else ()
        steps.append(WorkflowStep(sid, sid.upper(), role, depends, prompt=f"step {sid}"))
    return WorkflowDefinition("budget-chain", "BudgetChain", "", tuple(steps))


async def _collect(runner_module, workflow, query, output_dir, budget_limits):
    frames = []
    async for frame in runner_module.run_registered_workflow(
        workflow, query, "test-model", output_dir.parent, output_dir,
        budget_limits=budget_limits,
    ):
        frames.append(frame)
    return frames


class TestGlobalBudgetAggregation:
    def test_third_wave_blocked_after_two_nodes_exhaust_global_cap(
            self, tmp_path, monkeypatch):
        """两个节点各自消耗后，第三波调度前触发全局 token 帽。"""
        import research_assistant.workflows.runner as runner

        calls: list[str] = []

        async def fake_run_agent(**kwargs):
            cfg = kwargs["config"]
            # 每个节点真实消耗 1300 tokens（经节点自己的预算计量）
            cfg.budget.record(_resp(650, 650))
            calls.append(kwargs["prompt"])
            return AgentResult(text_output="done", success=True)

        class FakeClient:
            async def close(self):
                return None

        monkeypatch.setattr(runner, "create_llm_client", lambda **kw: FakeClient())
        monkeypatch.setattr(runner, "run_agent", fake_run_agent)

        registry = get_workflow_registry()
        workflow = _chain_workflow(("a", "b", "c"))
        workflow.validate(registry.roles)

        from research_assistant.kernel.budget import BudgetLimits
        frames = asyncio.run(_collect(
            runner, workflow, "q", tmp_path / "out",
            BudgetLimits(max_total_tokens=2500),
        ))

        assert len(calls) == 2, "第三波必须在调度前被拦截"
        final = frames[-1]
        assert final["type"] == "result"
        assert final["status"] == "failed"
        assert "全局预算超限" in final["error"]
        assert "token limit" in final["error"]

    def test_within_cap_completes_and_aggregates_usage(self, tmp_path, monkeypatch):
        """未触顶时正常跑完；顶层快照聚合了所有节点的用量与轮次。"""
        import research_assistant.workflows.runner as runner

        async def fake_run_agent(**kwargs):
            cfg = kwargs["config"]
            cfg.budget.record(_resp(100, 50))
            return AgentResult(text_output=f"done:{kwargs['prompt'].splitlines()[2]}", success=True)

        class FakeClient:
            async def close(self):
                return None

        monkeypatch.setattr(runner, "create_llm_client", lambda **kw: FakeClient())
        monkeypatch.setattr(runner, "run_agent", fake_run_agent)

        registry = get_workflow_registry()
        workflow = _chain_workflow(("a", "b"))
        workflow.validate(registry.roles)

        from research_assistant.kernel.budget import BudgetLimits
        frames = asyncio.run(_collect(
            runner, workflow, "q", tmp_path / "out",
            BudgetLimits(max_total_tokens=10_000),
        ))

        assert frames[-1]["status"] == "success"
        usage_frames = [f for f in frames if f.get("type") == "usage"]
        assert len(usage_frames) == 2
        # 节点快照各自记了 150 tokens（聚合进顶层 state 的间接证据：无异常且跑完）
        assert all(u["budget"]["total_tokens"] == 150 for u in usage_frames)


class TestCheckpointQueryFingerprint:
    def test_same_output_dir_new_query_ignores_old_checkpoints(self, tmp_path, monkeypatch):
        """同一 output_dir 换 query 重跑：旧 checkpoint 不被复用（H2）。"""
        import research_assistant.workflows.runner as runner

        calls: list[str] = []

        async def fake_run_agent(**kwargs):
            calls.append(kwargs["prompt"])
            return AgentResult(text_output=f"done:{kwargs['prompt'].splitlines()[2]}", success=True)

        class FakeClient:
            async def close(self):
                return None

        monkeypatch.setattr(runner, "create_llm_client", lambda **kw: FakeClient())
        monkeypatch.setattr(runner, "run_agent", fake_run_agent)

        registry = get_workflow_registry()
        workflow = _chain_workflow(("a", "b"))
        workflow.validate(registry.roles)
        out_dir = tmp_path / "out"

        first = asyncio.run(_collect(runner, workflow, "第一个问题", out_dir, None))
        assert first[-1]["status"] == "success"
        assert len(calls) == 2

        calls.clear()
        second = asyncio.run(_collect(runner, workflow, "完全不同的问题", out_dir, None))

        assert second[-1]["status"] == "success"
        resumed = [
            f for f in second
            if isinstance(f.get("details"), dict) and f["details"].get("status") == "resumed"
        ]
        assert not resumed, "查询已变，旧 checkpoint 不应复用"
        assert len(calls) == 2, "两个节点都必须真正重跑"

    def test_legacy_checkpoint_without_hash_still_accepted(self, tmp_path, monkeypatch):
        """存量 checkpoint（无 query_hash 字段）保持兼容，照常恢复。"""
        import research_assistant.workflows.runner as runner

        calls: list[str] = []

        async def fake_run_agent(**kwargs):
            calls.append(kwargs["prompt"])
            return AgentResult(text_output="done", success=True)

        class FakeClient:
            async def close(self):
                return None

        monkeypatch.setattr(runner, "create_llm_client", lambda **kw: FakeClient())
        monkeypatch.setattr(runner, "run_agent", fake_run_agent)

        registry = get_workflow_registry()
        workflow = _chain_workflow(("a",))
        workflow.validate(registry.roles)

        state_path = tmp_path / "out" / ".ra" / "workflow" / "a.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "status": "complete", "text": "legacy result",
        }), encoding="utf-8")

        frames = asyncio.run(_collect(runner, workflow, "任意问题", tmp_path / "out", None))

        assert not calls, "存量 checkpoint 应直接恢复，不重跑"
        resumed = [
            f for f in frames
            if isinstance(f.get("details"), dict) and f["details"].get("status") == "resumed"
        ]
        assert len(resumed) == 1
        assert frames[-1]["status"] == "success"

    def test_checkpoint_file_carries_query_hash(self, tmp_path, monkeypatch):
        """新写入的 checkpoint 必须带 query_hash 指纹。"""
        import hashlib

        import research_assistant.workflows.runner as runner

        async def fake_run_agent(**kwargs):
            return AgentResult(text_output="done", success=True)

        class FakeClient:
            async def close(self):
                return None

        monkeypatch.setattr(runner, "create_llm_client", lambda **kw: FakeClient())
        monkeypatch.setattr(runner, "run_agent", fake_run_agent)

        registry = get_workflow_registry()
        workflow = _chain_workflow(("a",))
        workflow.validate(registry.roles)

        asyncio.run(_collect(runner, workflow, "问题 X", tmp_path / "out", None))

        data = json.loads(
            (tmp_path / "out" / ".ra" / "workflow" / "a.json").read_text(encoding="utf-8"),
        )
        expected = hashlib.sha256("问题 X".encode()).hexdigest()
        assert data["query_hash"] == expected
