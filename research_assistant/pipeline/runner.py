"""Pipeline state machine — resumable, gated document generation.

Stages:
    PLAN -> RESEARCH(parallel) + FIGURES(parallel) -> ASSEMBLE
         -> GATES -> (REVISION <= N) -> FINALIZE

Every stage writes content-addressed artifacts (see artifacts.ArtifactStore);
on resume, stages whose artifacts are unchanged are skipped. A single
BudgetGuard and cancel_event span all sub-agents. Yields the same
progress/text/result dict shapes as the legacy orchestrator so hosts can
consume either interchangeably.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from ..agent import AgentResult as LoopResult
from ..agent import RunConfig, run_agent
from ..kernel.budget import BudgetGuard, BudgetLimits
from ..kernel.events import HookBus
from ..llm.factory import create_llm_client
from ..models import ProgressUpdate, TextUpdate
from ..orchestrator import (
    _FIGURE_PROMPT,
    _PLANNER_PROMPT,
    _RESEARCH_PROMPT,
    _parse_plan,
    _sanitize_filename,
)
from .artifacts import ArtifactStore

_ASSEMBLE_PROMPT = """Write the complete paper using python-docx via the run_python tool.

Title: {paper_title}
Type: {paper_type}
Venue: {venue}
Target words: {total_words}
Target citations: {citation_target}

Sections: {sections_info}
Research summaries (read the full files with read_file before writing):
{research_summaries}
Figures: {figures_info}

Merge every BibTeX entry from these files into ONE file: {bib_file}
Then create the .docx at: {docx_file}

Use the run_python tool:

```python
from research_assistant.docgen import PaperBuilder, Reference, parse_bibtex
paper = PaperBuilder("{paper_title}", authors=["[Author Name]"])
# ... add_section/add_figure/add_references_from_bibtex ...
paper.save(r"{docx_file}")
```

Cite only papers present in the BibTeX files. Every section must be written in full."""

_REVISION_PROMPT = """The generated paper FAILED quality gates. Fix it.

Paper directory: {output_dir}
Document: {docx_file}
BibTeX: {bib_file}

Gate report:
{gate_report}

Instructions:
1. read_file the gate report details above; fix EVERY listed failure
2. Regenerate the .docx via run_python (increment the version: v{n}_draft.docx is current, write v{n_next}_draft.docx)
3. Do not remove content that passed — only fix what failed"""

_REVIEW_PROMPT = """Review the finished paper in {output_dir}.

1. read_file the final .docx path: {docx_file}
2. Write {output_dir}/PEER_REVIEW.md — strengths, weaknesses, actionable fixes
3. Write {output_dir}/SUMMARY.md — what was produced, file map, how to edit"""


async def _run_stage_agent(
    stage_name: str,
    prompt: str,
    system_prompt: str,
    *,
    model: str,
    work_dir: Path,
    api_key: str | None,
    base_url: str | None,
    provider: str | None,
    budget: BudgetGuard,
    hooks: HookBus,
    cancel_event: asyncio.Event | None,
    auto_continue: bool = True,
    max_continuations: int = 10,
    approver: Any | None = None,
    session_log: Any | None = None,
    steer_queue: asyncio.Queue | None = None,
) -> LoopResult:
    """One sub-agent run inside the pipeline, sharing budget/hooks/cancel."""
    llm_client = create_llm_client(
        api_key=api_key, base_url=base_url, model=model, provider=provider,
    )
    tools = _tools_for(work_dir)
    try:
        return await run_agent(
            prompt=prompt,
            system_prompt=system_prompt,
            llm_client=llm_client,
            tools=tools,
            config=RunConfig(
                budget=budget,
                hooks=hooks,
                cancel_event=cancel_event,
                auto_continue=auto_continue,
                max_continuations=max_continuations,
                approver=approver,
                session_log=session_log,
            ),
            steer_queue=steer_queue,  # B4: 中途转向注入当前子代理
        )
    finally:
        await llm_client.close()


def _tools_for(work_dir: Path):
    from ..tools.registry import ToolRegistry
    return ToolRegistry(work_dir=str(work_dir))


def _p(msg: str, stage: str) -> dict:
    return ProgressUpdate(message=msg, stage=stage).to_dict()


def _t(content: str) -> dict:
    return TextUpdate(content=f"{content}\n").to_dict()


async def run_pipeline(
    query: str,
    model: str,
    work_dir: Path,
    output_dir: Path,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    provider: str | None = None,
    max_parallel_sections: int = 4,
    max_parallel_figures: int = 4,
    cancel_event: asyncio.Event | None = None,
    hooks: HookBus | None = None,
    budget_limits: BudgetLimits | None = None,
    approver: Any | None = None,
    max_revision_rounds: int = 3,
    steer_queue: asyncio.Queue | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Execute the full generation pipeline, yielding progress updates.

    Args:
        steer_queue: Optional queue with mid-run user steering messages (B4).
            All sub-agents share it — whoever is running at the moment consumes
            the message, mirroring the CLI steer channel semantics.
    """
    from ..api import usage_ticks  # lazy: api 与本模块互相延迟导入避免循环
    from ..constants import OUTPUT_SUBDIRS

    total_start = time.time()
    work_dir = Path(work_dir)
    output_dir = Path(output_dir)
    for subdir in OUTPUT_SUBDIRS:
        (output_dir / subdir).mkdir(parents=True, exist_ok=True)

    store = ArtifactStore(output_dir)
    from ..session.store import SessionStore
    session = SessionStore.create(output_dir, query=query, model=model, mode="pipeline")

    hooks = hooks or HookBus()
    budget = BudgetGuard(limits=budget_limits or BudgetLimits.from_env(), model=model)

    def _cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    if _cancelled():
        session.finish("cancelled", budget.snapshot())
        yield _t("Cancelled before start.")
        return

    def _stage_kwargs(**kw: Any) -> dict[str, Any]:
        return dict(
            model=model, work_dir=work_dir,
            api_key=api_key, base_url=base_url, provider=provider,
            budget=budget, hooks=hooks, cancel_event=cancel_event,
            approver=approver,
            # B4: 并行研究/图表阶段共享同一转向队列——谁在运行谁消费。
            steer_queue=steer_queue,
            session_log=session,  # SessionStore has .log()
            **kw,
        )

    async def _run_stage(
        stage: str, prompt: str, system_prompt: str, **kw: Any,
    ) -> LoopResult:
        result = await _run_stage_agent(stage, prompt, system_prompt, **_stage_kwargs(**kw))
        session.log_event(f"stage_{stage}", {
            "stop_reason": result.stop_reason, "turns": result.turns,
            "tokens": result.token_usage.input_tokens + result.token_usage.output_tokens,
        })
        return result

    async def _agent(
        stage: str, prompt: str, system_prompt: str, out: list, **kw: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Run one top-level stage, streaming budget usage frames meanwhile (B5).

        The :class:`LoopResult` is appended to *out* — callers pass a fresh
        one-element list and read ``out[0]`` after the loop (an async generator
        cannot both yield frames and return the result cleanly).
        """
        task = asyncio.ensure_future(_run_stage(stage, prompt, system_prompt, **kw))
        async for frame in usage_ticks(task, budget):
            yield frame
        out.append(task.result())

    # ------------------------------------------------------------------ PLAN
    plan: Any = None
    if store.is_valid("plan.json"):
        data = json.loads(Path(store.get("plan.json").path).read_text(encoding="utf-8"))
        plan = _parse_plan(json.dumps(data))
        session.mark_stage("plan", "skipped")
        yield _p("[resume] Plan loaded from artifacts.", "planning")
    else:
        session.mark_stage("plan", "running")
        yield _p("[Phase 1] Planning paper structure...", "planning")
        box: list[LoopResult] = []
        async for frame in _agent(
            "plan", _PLANNER_PROMPT.format(query=query),
            "You are a planning agent. Output only valid JSON.",
            box, auto_continue=False, max_continuations=5,
        ):
            yield frame
        result = box[0]
        if _cancelled():
            session.finish("cancelled", budget.snapshot())
            yield _t("Cancelled.")
            return
        try:
            if not result.success or not result.text_output.strip():
                raise ValueError(result.error or "empty planner output")
            plan = _parse_plan(result.text_output)
        except Exception as e:
            session.mark_stage("plan", "failed", error=str(e))
            session.finish("failed", budget.snapshot())
            yield _t(f"Planning failed: {e}")
            return
        plan_file = output_dir / ".ra" / "artifacts" / "plan.json"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text(json.dumps({
            "paper_title": plan.paper_title, "paper_type": plan.paper_type,
            "venue": plan.venue,
            "sections": [{"name": s.name, "title": s.title, "description": s.description,
                          "estimated_words": s.estimated_words,
                          "search_queries": s.search_queries} for s in plan.sections],
            "figures": [{"name": fg.name, "description": fg.description, "type": fg.type,
                         "filename": fg.filename} for fg in plan.figures],
            "total_estimated_words": plan.total_estimated_words,
            "citation_target": plan.citation_target,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        store.register("plan.json", plan_file, stage="plan")
        session.mark_stage("plan", "done", artifacts=["plan.json"])

    yield _t(f"Plan: {plan.paper_title} "
             f"({len(plan.sections)} sections, {len(plan.figures)} figures)")

    sources_dir = output_dir / "sources"
    figures_dir = output_dir / "figures"

    # ------------------------------------------------- RESEARCH + FIGURES
    session.mark_stage("research_figures", "running")
    yield _p(f"[Phase 2] {len(plan.sections)} research + "
             f"{len(plan.figures)} figure agents...", "research")

    sem = asyncio.Semaphore(max_parallel_sections + max_parallel_figures)

    async def _limited(coro):
        async with sem:
            return await coro

    async def _research_one(s):
        safe = _sanitize_filename(s.name, default="section")
        summary_key, bib_key = f"summary_{safe}", f"bib_{safe}"
        if store.all_valid(summary_key, bib_key):
            return (s.name, True, "resumed", 0.0)
        started = time.time()
        out_bib = sources_dir / f"bib_{safe}.bib"
        out_sum = sources_dir / f"summary_{safe}.md"
        r = await _run_stage(
            f"research_{safe}",
            _RESEARCH_PROMPT.format(
                section_title=s.title, paper_title=plan.paper_title,
                section_description=s.description, venue=plan.venue,
                search_queries="\n".join(f"- {q}" for q in s.search_queries),
                output_file=out_bib, summary_file=out_sum,
            ),
            "You are a research agent. Find REAL papers. Write BibTeX. Never fabricate.",
            max_continuations=10,
        )
        ok = out_sum.exists() and out_bib.exists() and r.success
        if out_sum.exists():
            store.register(summary_key, out_sum, stage="research")
        if out_bib.exists():
            store.register(bib_key, out_bib, stage="research")
        return (s.name, bool(ok), "ok" if ok else (r.error or "files missing"),
                time.time() - started)

    async def _figure_one(fg):
        safe = _sanitize_filename(fg.filename or f"{fg.name}.png", default="figure.png")
        key = f"figure_{safe}"
        if store.is_valid(key):
            return (fg.name, True, "resumed", 0.0)
        started = time.time()
        out = figures_dir / safe
        r = await _run_stage(
            f"figure_{fg.name}",
            _FIGURE_PROMPT.format(
                paper_title=plan.paper_title, figure_name=fg.name,
                figure_description=fg.description, figure_type=fg.type,
                output_file=out, cwd=str(work_dir), description=fg.description,
            ),
            "You are a figure generation agent. Generate figures using scripts.",
            auto_continue=False, max_continuations=5,
        )
        ok = out.exists()
        if ok:
            store.register(key, out, stage="figures")
        return (fg.name, bool(ok), "ok" if ok else (r.error or "file missing"),
                time.time() - started)

    tasks = [_limited(_research_one(s)) for s in plan.sections]
    tasks += [_limited(_figure_one(fg)) for fg in plan.figures]
    # B5: gather 期间没有其他 yield 点，用 usage_ticks 周期推送预算快照。
    gather_task = asyncio.ensure_future(
        asyncio.gather(*tasks, return_exceptions=True),
    )
    async for frame in usage_ticks(gather_task, budget):
        yield frame
    outcomes = gather_task.result()

    partial = False
    labels = [f"research:{s.name}" for s in plan.sections] + \
             [f"figure:{fg.name}" for fg in plan.figures]
    for label, outcome in zip(labels, outcomes, strict=False):
        if isinstance(outcome, Exception):
            partial = True
            yield _t(f"  [{label}] FAILED: {outcome}")
        else:
            name, ok, note, dur = outcome
            if not ok:
                partial = True
            yield _t(f"  [{label}] {'OK' if ok else 'FAILED'}: {note} ({dur:.1f}s)")

    session.mark_stage("research_figures", "partial" if partial else "done")

    # ------------------------------------------------------------- ASSEMBLE
    session.mark_stage("assemble", "running")
    yield _p("[Phase 3] Assembling paper...", "writing")

    docx_file = output_dir / "drafts" / "v1_draft.docx"
    bib_file = output_dir / "references" / "references.bib"

    def _summaries_text() -> str:
        parts = []
        for s in plan.sections:
            safe = _sanitize_filename(s.name, default="section")
            key = f"summary_{safe}"
            entry = store.get(key)
            if entry and Path(entry.path).exists():
                body = Path(entry.path).read_text(encoding="utf-8")[:6_000]
                parts.append(f"### {s.title}\nFile: {entry.path}\n{body}")
        return "\n\n".join(parts) or "(no summaries found)"

    box = []
    async for frame in _agent(
        "assemble",
        _ASSEMBLE_PROMPT.format(
            paper_title=plan.paper_title, paper_type=plan.paper_type,
            venue=plan.venue, total_words=plan.total_estimated_words,
            citation_target=plan.citation_target,
            sections_info="\n".join(
                f"- {s.title}: {s.description} (~{s.estimated_words} words)"
                for s in plan.sections),
            research_summaries=_summaries_text(),
            figures_info="\n".join(
                f"- {fg.name}: {figures_dir / _sanitize_filename(fg.filename or f'{fg.name}.png', default='figure.png')}"
                for fg in plan.figures),
            docx_file=docx_file, bib_file=bib_file,
        ),
        "Write a complete paper using PaperBuilder via run_python. "
        "Include all figures and references.",
        box, max_continuations=12,
    ):
        yield frame
    assemble_result = box[0]
    if _cancelled():
        session.finish("cancelled", budget.snapshot())
        yield _t("Cancelled.")
        return

    # Robustness: merge per-section bibs when assembly didn't produce one.
    if not bib_file.exists():
        bib_file.parent.mkdir(parents=True, exist_ok=True)
        merged = []
        for s in plan.sections:
            safe = _sanitize_filename(s.name, default="section")
            p = sources_dir / f"bib_{safe}.bib"
            if p.exists():
                merged.append(p.read_text(encoding="utf-8"))
        bib_file.write_text("\n\n".join(merged), encoding="utf-8")

    if not docx_file.exists():
        session.mark_stage("assemble", "failed",
                           error=assemble_result.error or "no docx produced")
        session.finish("failed", budget.snapshot())
        yield _t(f"[Assembly] FAILED: no document produced. "
                 f"{assemble_result.error or ''}")
        return

    store.register("draft_docx", docx_file, stage="assemble")
    if bib_file.exists():
        store.register("references_bib", bib_file, stage="assemble")
    session.mark_stage("assemble", "done", artifacts=["draft_docx"])
    yield _t("  [Assembly] Paper written.")

    # ------------------------------------------------------------ GATES LOOP
    from ..gates import CitationGate, DocGate, GateReport, render_gate_report_md

    expected_sections = [s.title for s in plan.sections]

    async def _run_gates(round_no: int) -> GateReport:
        report = GateReport(revision_round=round_no)
        citation = await CitationGate(
            bib_file,
            report_output=output_dir / "sources" / "CITATION_VERIFICATION.md",
        ).run({})
        doc = await DocGate(
            docx_file,
            expected_sections=expected_sections,
            figures_dir=figures_dir,
            target_words=plan.total_estimated_words or None,
        ).run({})
        report.results.extend([citation, doc])
        report.save(output_dir / "gates_report.json")
        session.log_event("gates", {"round": round_no, "passed": report.passed})
        return report

    session.mark_stage("gates", "running")
    gate_report = await _run_gates(round_no=0)
    revision_round = 0

    while not gate_report.passed and revision_round < max_revision_rounds:
        if _cancelled():
            session.finish("cancelled", budget.snapshot())
            yield _t("Cancelled.")
            return
        revision_round += 1
        yield _p(f"[Phase 3b] Quality gates failed — revision round "
                 f"{revision_round}/{max_revision_rounds}", "revision")
        box = []
        async for frame in _agent(
            f"revision_{revision_round}",
            _REVISION_PROMPT.format(
                output_dir=output_dir, docx_file=docx_file, bib_file=bib_file,
                gate_report=render_gate_report_md(gate_report),
                n=revision_round, n_next=revision_round + 1,
            ),
            "Fix every quality-gate failure. Regenerate the document.",
            box, max_continuations=10,
        ):
            yield frame
        latest = output_dir / "drafts" / f"v{revision_round + 1}_draft.docx"
        if latest.exists():
            docx_file = latest
        gate_report = await _run_gates(revision_round)

    session.mark_stage("gates", "done" if gate_report.passed else "partial")

    # -------------------------------------------------------------- FINALIZE
    session.mark_stage("finalize", "running")
    yield _p("[Phase 4] Finalizing...", "finalization")

    final_dir = output_dir / "final"
    final_dir.mkdir(exist_ok=True)
    final_docx = final_dir / "manuscript.docx"
    shutil.copy2(docx_file, final_docx)

    if not _cancelled():
        try:
            box = []
            async for frame in _agent(
                "review",
                _REVIEW_PROMPT.format(output_dir=output_dir, docx_file=final_docx),
                "Review the paper document and write PEER_REVIEW.md and SUMMARY.md.",
                box, auto_continue=False, max_continuations=8,
            ):
                yield frame
        except Exception as e:  # review is best-effort
            yield _t(f"  [Review] skipped: {e}")

    total_duration = time.time() - total_start
    session.finish(
        "complete" if gate_report.passed else "partial",
        budget.snapshot(),
    )
    yield _p(f"Pipeline complete in {total_duration:.0f}s "
             f"(gates: {'PASS' if gate_report.passed else 'PARTIAL'}, "
             f"cost ${budget.state.cost_usd:.2f})", "complete")

    from ..api import _build_paper_result  # lazy to avoid circular import
    from ..utils import scan_paper_directory
    file_info = scan_paper_directory(output_dir)
    yield _build_paper_result(output_dir, file_info).to_dict()
