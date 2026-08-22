"""Tests for pipeline: artifacts, session store, and the state-machine runner.

The runner tests monkeypatch the sub-agent entry point so no LLM or network
is involved; the citation gate is stubbed to an all-verified report.
"""

import json
import re
from pathlib import Path

import pytest

from research_assistant.pipeline.artifacts import ArtifactStore
from research_assistant.session.store import SessionStore


# ---------------------------------------------------------------------------
# ArtifactStore
# ---------------------------------------------------------------------------

class TestArtifactStore:
    def test_register_and_valid(self, tmp_path):
        store = ArtifactStore(tmp_path)
        f = tmp_path / "plan.json"
        f.write_text('{"a": 1}')
        store.register("plan.json", f, stage="plan")
        assert store.is_valid("plan.json")

    def test_content_change_invalidates(self, tmp_path):
        store = ArtifactStore(tmp_path)
        f = tmp_path / "plan.json"
        f.write_text("v1")
        store.register("k", f, stage="plan")
        f.write_text("v2")
        assert not store.is_valid("k")

    def test_missing_file_invalid(self, tmp_path):
        store = ArtifactStore(tmp_path)
        f = tmp_path / "gone.txt"
        f.write_text("x")
        store.register("k", f, stage="s")
        f.unlink()
        assert not store.is_valid("k")

    def test_manifest_persists_across_instances(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("data")
        ArtifactStore(tmp_path).register("a", f, stage="s")
        again = ArtifactStore(tmp_path)
        assert again.is_valid("a")
        assert again.get("a").stage == "s"

    def test_all_valid(self, tmp_path):
        store = ArtifactStore(tmp_path)
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_text("1"); b.write_text("2")
        store.register("a", a, stage="s")
        store.register("b", b, stage="s")
        assert store.all_valid("a", "b")
        b.write_text("changed")
        assert not store.all_valid("a", "b")


# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------

class TestSessionStore:
    def test_create_and_reload(self, tmp_path):
        SessionStore.create(tmp_path, query="q", model="m")
        reloaded = SessionStore(tmp_path)
        assert reloaded.state.query == "q"
        assert reloaded.state.model == "m"
        assert reloaded.state.status == "running"

    def test_mark_stage_lifecycle(self, tmp_path):
        store = SessionStore.create(tmp_path, query="q", model="m")
        store.mark_stage("plan", "running")
        store.mark_stage("plan", "done", artifacts=["plan.json"])
        assert store.stage_status("plan") == "done"
        assert store.done_stages() == ["plan"]
        rec = store.state.stages["plan"]
        assert rec["finished_at"] > 0
        assert rec["artifacts"] == ["plan.json"]

    def test_events_append_and_read(self, tmp_path):
        store = SessionStore.create(tmp_path, query="q", model="m")
        store.log_event("stage_plan", {"n": 1})
        store.log_event("gates", {"passed": True})
        events = SessionStore(tmp_path).read_events()
        assert [e["kind"] for e in events] == ["stage_plan", "gates"]
        assert events[0]["data"]["n"] == 1

    def test_finish(self, tmp_path):
        store = SessionStore.create(tmp_path, query="q", model="m")
        store.finish("complete", budget.snapshot() if (budget := None) else {"cost_usd": 0.5})
        reloaded = SessionStore(tmp_path)
        assert reloaded.state.status == "complete"
        assert reloaded.state.budget["cost_usd"] == 0.5

    def test_corrupt_run_json_tolerated(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        (tmp_path / "run.json").write_text("{not json", encoding="utf-8")
        store = SessionStore(tmp_path)
        assert store.state.status == "running"  # fresh state, no crash


# ---------------------------------------------------------------------------
# Runner (sub-agents faked)
# ---------------------------------------------------------------------------

PLAN_JSON = {
    "paper_title": "Test Paper on FEM",
    "paper_type": "research_paper",
    "venue": "ASCE",
    "sections": [
        {"name": "introduction", "title": "Introduction",
         "description": "intro", "estimated_words": 100,
         "search_queries": ["fem"]},
        {"name": "methods", "title": "Methods",
         "description": "methods", "estimated_words": 100,
         "search_queries": ["fem"]},
    ],
    "figures": [],
    "total_estimated_words": 200,
    "citation_target": 4,
}


def _extract(prompt: str, pattern: str) -> str:
    m = re.search(pattern, prompt)
    return m.group(1).strip() if m else ""


def _make_fake_agent(calls: list, workdir_holder: dict):
    """Build a fake _run_stage_agent that creates the files each stage promises."""

    async def fake_agent(stage_name, prompt, system_prompt, *, model, work_dir,
                         api_key, base_url, provider, budget, hooks, cancel_event,
                         auto_continue=True, max_continuations=10,
                         approver=None, session_log=None, steer_queue=None):
        calls.append(stage_name)
        from research_assistant.agent import AgentResult

        if stage_name == "plan":
            return AgentResult(text_output=json.dumps(PLAN_JSON), stop_reason="completed")

        if stage_name.startswith("research_"):
            bib = Path(_extract(prompt, r"Write BibTeX entries to: (.+)"))
            summary = Path(_extract(prompt, r"Write a summary to: (.+)"))
            bib.parent.mkdir(parents=True, exist_ok=True)
            bib.write_text(
                "@article{real2024, author={A}, title={Real Paper},\n"
                " journal={J}, year={2024}}\n"
            )
            summary.write_text(f"Summary for {stage_name}\nkey findings here")
            return AgentResult(stop_reason="completed")

        if stage_name.startswith("figure_"):
            out = Path(_extract(prompt, r"Output: (.+)"))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"png")
            return AgentResult(stop_reason="completed")

        if stage_name == "assemble":
            docx = Path(_extract(prompt, r"Then create the \.docx at: (.+)"))
            docx.parent.mkdir(parents=True, exist_ok=True)
            from docx import Document
            doc = Document()
            for s in PLAN_JSON["sections"]:
                doc.add_heading(s["title"], level=1)
                doc.add_paragraph(" ".join(["data"] * 150))
            doc.save(str(docx))
            # merge bib as the real agent would
            bib_file = Path(_extract(prompt, r"ONE file: (.+)"))
            bib_file.parent.mkdir(parents=True, exist_ok=True)
            if not bib_file.exists():
                srcs = sorted(bib_file.parent.parent.glob("sources/bib_*.bib"))
                bib_file.write_text("\n".join(
                    p.read_text(encoding="utf-8") for p in srcs))
            return AgentResult(stop_reason="completed")

        if stage_name.startswith("revision_"):
            raise AssertionError("gates should pass; revision must not run")

        if stage_name == "review":
            out_dir = Path(_extract(prompt, r"Write (.+)/PEER_REVIEW\.md"))
            (out_dir / "PEER_REVIEW.md").write_text("# review")
            (out_dir / "SUMMARY.md").write_text("# summary")
            return AgentResult(stop_reason="completed")

        raise AssertionError(f"unexpected stage {stage_name}")

    return fake_agent


@pytest.fixture
def gate_stub(monkeypatch):
    """CitationGate that always passes without network."""
    from research_assistant.gates import GateResult
    import research_assistant.gates as gates_pkg

    class StubCitationGate(gates_pkg.CitationGate):
        async def run(self, context):
            return GateResult(name="citations", passed=True,
                              details={"stubbed": True})

    monkeypatch.setattr(gates_pkg, "CitationGate", StubCitationGate)


async def _collect(agen):
    outs = []
    async for u in agen:
        outs.append(u)
    return outs


@pytest.mark.asyncio
async def test_full_pipeline_happy_path(tmp_path, monkeypatch, gate_stub):
    calls: list = []
    monkeypatch.setattr(
        "research_assistant.pipeline.runner._run_stage_agent",
        _make_fake_agent(calls, {}),
    )
    from research_assistant.pipeline.runner import run_pipeline

    out_dir = tmp_path / "writing_outputs" / "run1"
    updates = await _collect(run_pipeline(
        query="write a fem paper", model="test-model",
        work_dir=tmp_path, output_dir=out_dir,
    ))

    types = [u.get("type") for u in updates]
    assert "result" in types
    final = next(u for u in updates if u["type"] == "result")
    assert final["status"] == "success"
    assert (out_dir / "final" / "manuscript.docx").exists()
    assert (out_dir / "gates_report.json").exists()

    session = SessionStore(out_dir)
    assert session.state.status == "complete"
    assert session.stage_status("assemble") == "done"
    kinds = [e["kind"] for e in session.read_events()]
    assert "run_end" in kinds

    report = json.loads((out_dir / "gates_report.json").read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert "revision_1" not in calls


@pytest.mark.asyncio
async def test_pipeline_resume_skips_completed_stages(tmp_path, monkeypatch, gate_stub):
    calls: list = []
    monkeypatch.setattr(
        "research_assistant.pipeline.runner._run_stage_agent",
        _make_fake_agent(calls, {}),
    )
    from research_assistant.pipeline.runner import run_pipeline

    out_dir = tmp_path / "run"
    await _collect(run_pipeline("q", "m", tmp_path, out_dir))
    first_run_calls = list(calls)
    assert any(c.startswith("research_") for c in first_run_calls)

    # Simulate crash after assembly: wipe drafts + final but keep artifacts.
    import shutil
    shutil.rmtree(out_dir / "drafts")
    shutil.rmtree(out_dir / "final")

    calls.clear()
    await _collect(run_pipeline("q", "m", tmp_path, out_dir))

    # Research/figure/plan stages must NOT rerun — artifacts were valid.
    assert not any(c.startswith("research_") for c in calls)
    assert not any(c.startswith("figure_") for c in calls)
    assert "plan" not in calls
    assert "assemble" in calls  # its artifact was deleted -> must regenerate
    assert (out_dir / "final" / "manuscript.docx").exists()


@pytest.mark.asyncio
async def test_pipeline_cancel_before_start(tmp_path, monkeypatch, gate_stub):
    import asyncio
    cancel = asyncio.Event()
    cancel.set()
    calls: list = []
    monkeypatch.setattr(
        "research_assistant.pipeline.runner._run_stage_agent",
        _make_fake_agent(calls, {}),
    )
    from research_assistant.pipeline.runner import run_pipeline

    out_dir = tmp_path / "run"
    updates = await _collect(run_pipeline(
        "q", "m", tmp_path, out_dir, cancel_event=cancel,
    ))
    assert calls == []
    session = SessionStore(out_dir)
    assert session.state.status == "cancelled"


@pytest.mark.asyncio
async def test_pipeline_records_budget_snapshot(tmp_path, monkeypatch, gate_stub):
    from research_assistant.kernel.budget import BudgetLimits
    calls: list = []
    monkeypatch.setattr(
        "research_assistant.pipeline.runner._run_stage_agent",
        _make_fake_agent(calls, {}),
    )
    from research_assistant.pipeline.runner import run_pipeline

    out_dir = tmp_path / "run"
    await _collect(run_pipeline(
        "q", "claude-sonnet-4-6", tmp_path, out_dir,
        budget_limits=BudgetLimits(max_turns=100),
    ))
    state = SessionStore(out_dir).state
    assert state.budget["model"] == "claude-sonnet-4-6"
    assert state.budget["limits"]["max_turns"] == 100
