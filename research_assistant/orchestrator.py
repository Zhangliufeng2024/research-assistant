"""Multi-agent orchestrator for research assistant.

Decomposes a paper generation task into parallel sub-tasks:
  Phase 1: Planner agent -> section list + figure list
  Phase 2: N research agents (parallel) + M figure agents (parallel)
  Phase 3: Assembly agent -> writes final Word document via PaperBuilder
  Phase 4: Review agent -> quality check + fixes

Each agent is an independent agent loop session. Coordination through filesystem.
"""

import asyncio
import json
import re
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent import run_agent
from .constants import OUTPUT_SUBDIRS
from .core import execution_contract_addendum
from .llm.factory import create_llm_client
from .models import ProgressUpdate, TextUpdate, TokenUsage
from .tools.registry import ToolRegistry


def _sanitize_filename(name: str, default: str = "unnamed") -> str:
    """Sanitize an LLM-generated filename to prevent path traversal.

    Strips directory separators and ``..`` segments, keeping only the
    basename. Falls back to *default* if nothing remains.
    """
    basename = Path(name).name
    basename = re.sub(r'[^\w.\-]', '_', basename)
    return basename or default


@dataclass
class SectionPlan:
    name: str
    title: str
    description: str
    estimated_words: int = 500
    search_queries: list[str] = field(default_factory=list)


@dataclass
class FigurePlan:
    name: str
    description: str
    type: str = "schematic"
    filename: str = ""


@dataclass
class OrchestrationPlan:
    paper_title: str = ""
    paper_type: str = "research_paper"
    venue: str = ""
    sections: list[SectionPlan] = field(default_factory=list)
    figures: list[FigurePlan] = field(default_factory=list)
    total_estimated_words: int = 0
    citation_target: int = 30


@dataclass
class AgentResult:
    agent_id: str
    agent_role: str
    success: bool
    text_output: str = ""
    files_written: list[str] = field(default_factory=list)
    error: str | None = None
    duration_seconds: float = 0.0
    token_usage: TokenUsage | None = None


async def _run_sub_agent(  # noqa: PLR0913
    agent_id: str,
    agent_role: str,
    prompt: str,
    system_prompt: str,
    model: str,
    work_dir: Path,
    api_key: str | None = None,
    base_url: str | None = None,
    provider: str | None = None,
    auto_continue: bool = True,
    max_continuations: int = 20,
) -> "AgentResult":
    """Run a single sub-agent to completion."""
    llm_client = create_llm_client(
        api_key=api_key, base_url=base_url, model=model, provider=provider,
    )
    tool_registry = ToolRegistry(work_dir=str(work_dir))

    try:
        result = await run_agent(
            prompt=prompt,
            # R12 P1：legacy（RA_PIPELINE=false）路径同样注入执行契约
            system_prompt=system_prompt + execution_contract_addendum(),
            llm_client=llm_client,
            tools=tool_registry,
            auto_continue=auto_continue,
            max_continuations=max_continuations,
        )
        return AgentResult(
            agent_id=agent_id,
            agent_role=agent_role,
            success=True,
            text_output=result.text_output,
            files_written=result.files_written,
            duration_seconds=result.duration_seconds,
            token_usage=result.token_usage,
        )
    except Exception as e:
        return AgentResult(
            agent_id=agent_id,
            agent_role=agent_role,
            success=False,
            error=str(e),
        )
    finally:
        await llm_client.close()


# Plan parsing

def _extract_json_object(text: str) -> str:
    start = text.find('{')
    if start == -1:
        return ""
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


def _parse_plan(text: str) -> OrchestrationPlan:
    json_str = _extract_json_object(text)
    if not json_str:
        raise ValueError(f"Could not find JSON in planner output:\n{text[:500]}")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from planner: {e}\nRaw: {json_str[:500]}") from e

    plan = OrchestrationPlan(
        paper_title=data.get("paper_title", ""),
        paper_type=data.get("paper_type", "research_paper"),
        venue=data.get("venue", ""),
        total_estimated_words=data.get("total_estimated_words", 5000),
        citation_target=data.get("citation_target", 30),
    )

    for s in data.get("sections", []):
        plan.sections.append(SectionPlan(
            name=s.get("name", "unknown"),
            title=s.get("title", ""),
            description=s.get("description", ""),
            estimated_words=s.get("estimated_words", 500),
            search_queries=s.get("search_queries", []),
        ))

    for f in data.get("figures", []):
        plan.figures.append(FigurePlan(
            name=f.get("name", ""),
            description=f.get("description", ""),
            type=f.get("type", "schematic"),
            filename=f.get("filename", ""),
        ))

    return plan


# Prompt templates

_PLANNER_PROMPT = """You are a planning agent for scientific document generation.
Decompose this request into a structured plan.

User request: {query}

Output a JSON plan with this structure (no markdown, no code fences, just raw JSON):
{{
  "paper_title": "...",
  "paper_type": "research_paper | literature_review | grant_proposal | market_report",
  "venue": "Target journal/conference",
  "sections": [
    {{"name": "introduction", "title": "Introduction", "description": "...", "estimated_words": 800, "search_queries": ["query1", "query2"]}}
  ],
  "figures": [
    {{"name": "graphical_abstract", "description": "...", "type": "schematic", "filename": "graphical_abstract.png"}}
  ],
  "total_estimated_words": 5000,
  "citation_target": 30
}}

Rules:
- Scale the plan to the request. A focused task may need 2-4 sections; a full
  manuscript commonly needs 4-8. Do not create sections merely to hit a quota.
- Use 0-6 figures. Create a figure only when it materially supports a claim,
  result, method, or synthesis. A graphical abstract is optional unless asked.
- Prefer the smallest plan that can satisfy the requested scientific outcome.
- Output ONLY JSON"""

_RESEARCH_PROMPT = """You are a research agent for the section: {section_title}.
Find real, verifiable academic references.

Paper: {paper_title}
Section: {section_title} - {section_description}
Venue: {venue}
Search queries: {search_queries}

Write BibTeX entries to: {output_file}
Write a summary to: {summary_file}
Every citation MUST be real. Never fabricate."""

_FIGURE_PROMPT = """Create a scientific figure.

Paper: {paper_title}
Figure: {figure_name} - {figure_description}
Type: {figure_type}
Output (absolute path): {output_file}

Primary path — data plots with matplotlib via the run_python tool:

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(7, 4))
# ... plot from real data here ...
fig.savefig(r"{output_file}", dpi=200, bbox_inches="tight")
print("saved", r"{output_file}")
```

Secondary path (best effort) — concept schematics via run_script inside run_python:

```python
run_script(
    WS + r"/.claude/skills/scientific-schematics/scripts/generate_schematic.py",
    [r"{description}", "-o", r"{output_file}"],
)
```

Rules:
- NEVER invoke python/pip via bash or subprocess (packaged builds have no system Python).
- The output file MUST be exactly {output_file}; verify it exists after saving.
- If the schematic script fails, fall back to a clean matplotlib diagram."""

_ASSEMBLY_PROMPT = """Write the complete paper using python-docx via the run_python tool.

Title: {paper_title}
Type: {paper_type}
Venue: {venue}
Target words: {total_words}
Target citations: {citation_target}

Sections: {sections_info}
Research summaries: {research_summaries}
Figures: {figures_info}
BibTeX files: {bib_files}

Use the run_python tool to create the document with PaperBuilder:

```python
from research_assistant.docgen import PaperBuilder, Reference
paper = PaperBuilder("{paper_title}", authors=["[Author Name]"])
paper.add_section("Introduction", "content...")
paper.add_figure("figures/fig1.png", "Caption text")
paper.add_references([Reference(key="key", authors="...", title="...", year=2023, journal="...")])
paper.save("{docx_file}")
```

Also merge all BibTeX entries into: {bib_file}
Output directory: {output_dir}"""

_REVIEW_PROMPT = """Review the paper document.

Paper directory: {output_dir}

1. Read the generated .docx file and verify:
   - All sections present and complete
   - Figure references match actual figures
   - Citation numbers are sequential and correct
   - Word count meets target
   - No placeholder text remains

2. Fix any issues by regenerating the .docx via run_python (max 3 iterations)

3. Copy final version to final/manuscript.docx:
   import shutil
   shutil.copy2("{docx_file}", "{output_dir}/final/manuscript.docx")

4. Write PEER_REVIEW.md and SUMMARY.md"""


async def run_orchestrated_generation(
    query: str,
    model: str,
    work_dir: Path,
    output_dir: Path,
    api_key: str | None = None,
    base_url: str | None = None,
    provider: str | None = None,
    max_parallel_research: int = 4,
    max_parallel_figures: int = 4,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run the full multi-agent orchestration pipeline."""
    total_start = time.time()

    for subdir in OUTPUT_SUBDIRS:
        (output_dir / subdir).mkdir(parents=True, exist_ok=True)

    total_token_usage = TokenUsage()

    def _accum(result: AgentResult):
        if result.token_usage:
            total_token_usage.input_tokens += result.token_usage.input_tokens
            total_token_usage.output_tokens += result.token_usage.output_tokens
            total_token_usage.cache_creation_input_tokens += result.token_usage.cache_creation_input_tokens
            total_token_usage.cache_read_input_tokens += result.token_usage.cache_read_input_tokens

    # Phase 1: Planning
    yield ProgressUpdate(message="[Phase 1/4] Planning paper structure...", stage="planning").to_dict()

    try:
        planner_result = await _run_sub_agent(
            agent_id="planner", agent_role="Planner Agent",
            prompt=_PLANNER_PROMPT.format(query=query),
            system_prompt="You are a planning agent. Output only valid JSON.",
            model=model, work_dir=work_dir,
            api_key=api_key, base_url=base_url, provider=provider,
            auto_continue=False, max_continuations=5,
        )
        if not planner_result.success:
            yield TextUpdate(content=f"\nPlanning failed: {planner_result.error}\n").to_dict()
            return
        plan = _parse_plan(planner_result.text_output)
    except Exception as e:
        yield TextUpdate(content=f"\nPlanning failed: {e}\n").to_dict()
        return

    yield TextUpdate(content=f"\nPlan: {plan.paper_title} ({len(plan.sections)} sections, {len(plan.figures)} figures)\n").to_dict()

    plan_file = output_dir / "sources" / "orchestration_plan.json"
    with open(plan_file, "w", encoding="utf-8") as f:
        json.dump({
            "paper_title": plan.paper_title, "paper_type": plan.paper_type,
            "venue": plan.venue,
            "sections": [{"name": s.name, "title": s.title, "description": s.description,
                          "estimated_words": s.estimated_words, "search_queries": s.search_queries}
                         for s in plan.sections],
            "figures": [{"name": fg.name, "description": fg.description, "type": fg.type, "filename": fg.filename}
                        for fg in plan.figures],
            "total_estimated_words": plan.total_estimated_words,
            "citation_target": plan.citation_target,
        }, f, indent=2, ensure_ascii=False)

    # Phase 2: Parallel Research + Figures
    yield ProgressUpdate(
        message=f"[Phase 2/4] Running {len(plan.sections)} research + {len(plan.figures)} figure agents...",
        stage="research",
    ).to_dict()

    sources_dir = output_dir / "sources"
    figures_dir = output_dir / "figures"
    semaphore = asyncio.Semaphore(max_parallel_research + max_parallel_figures)

    async def _limited(coro):
        async with semaphore:
            return await coro

    research_coros = []
    for s in plan.sections:
        safe_name = _sanitize_filename(s.name, default="section")
        output_file = sources_dir / f"bib_{safe_name}.bib"
        summary_file = sources_dir / f"summary_{safe_name}.md"
        prompt = _RESEARCH_PROMPT.format(
            section_title=s.title, paper_title=plan.paper_title,
            section_description=s.description, venue=plan.venue,
            search_queries="\n".join(f"- {q}" for q in s.search_queries),
            output_file=str(output_file), summary_file=str(summary_file),
        )
        research_coros.append(_limited(_run_sub_agent(
            agent_id=f"research_{s.name}", agent_role=f"Research - {s.title}",
            prompt=prompt,
            system_prompt="You are a research agent. Find REAL papers. Write BibTeX. Never fabricate.",
            model=model, work_dir=work_dir,
            api_key=api_key, base_url=base_url, provider=provider,
            max_continuations=10,
        )))

    figure_coros = []
    for fg in plan.figures:
        safe_fig = _sanitize_filename(fg.filename or f"{fg.name}.png", default="figure.png")
        output_file = figures_dir / safe_fig
        prompt = _FIGURE_PROMPT.format(
            paper_title=plan.paper_title, figure_name=fg.name,
            figure_description=fg.description, figure_type=fg.type,
            output_file=str(output_file), cwd=str(work_dir),
            description=fg.description,
        )
        figure_coros.append(_limited(_run_sub_agent(
            agent_id=f"figure_{fg.name}", agent_role=f"Figure - {fg.name}",
            prompt=prompt,
            system_prompt="You are a figure generation agent. Generate figures using scripts.",
            model=model, work_dir=work_dir,
            api_key=api_key, base_url=base_url, provider=provider,
            auto_continue=False, max_continuations=5,
        )))

    all_coros = research_coros + figure_coros
    all_labels = [f"research_{s.name}" for s in plan.sections] + [f"figure_{fg.name}" for fg in plan.figures]

    all_results = await asyncio.gather(*all_coros, return_exceptions=True)

    research_results: list[AgentResult] = []
    figure_results: list[AgentResult] = []

    for i, result in enumerate(all_results):
        if isinstance(result, Exception):
            agent_result = AgentResult(agent_id=all_labels[i], agent_role=all_labels[i], success=False, error=str(result))
        else:
            agent_result = result

        _accum(agent_result)
        if i < len(plan.sections):
            research_results.append(agent_result)
        else:
            figure_results.append(agent_result)

        status = "OK" if agent_result.success else f"FAILED: {agent_result.error}"
        yield TextUpdate(content=f"  [{all_labels[i]}] {status} ({agent_result.duration_seconds:.1f}s)\n").to_dict()

    # Phase 3: Assembly
    yield ProgressUpdate(message="[Phase 3/4] Assembling paper...", stage="writing").to_dict()

    sections_info = "\n".join(f"- {s.title}: {s.description} (~{s.estimated_words} words)" for s in plan.sections)
    research_summaries = "\n".join(
        f"### {r.agent_role}\n{r.text_output[:2000]}" for r in research_results if r.success
    )
    figures_info = "\n".join(f"- {fg.name}: {fg.description} -> {fg.filename}" for fg in plan.figures)
    bib_files = "\n".join(f"- {r.files_written[0] if r.files_written else 'N/A'}" for r in research_results if r.success)

    output_dir / "drafts" / "v1_draft.tex"  # kept for legacy .tex input detection
    docx_file = output_dir / "drafts" / "v1_draft.docx"
    bib_file = output_dir / "references" / "references.bib"

    assembly_prompt = _ASSEMBLY_PROMPT.format(
        paper_title=plan.paper_title, paper_type=plan.paper_type, venue=plan.venue,
        total_words=plan.total_estimated_words, citation_target=plan.citation_target,
        sections_info=sections_info, research_summaries=research_summaries,
        figures_info=figures_info, bib_files=bib_files,
        docx_file=str(docx_file), bib_file=str(bib_file), output_dir=str(output_dir),
    )

    assembly_result = await _run_sub_agent(
        agent_id="assembly", agent_role="Assembly Agent",
        prompt=assembly_prompt,
        system_prompt="Write a complete paper using PaperBuilder via run_python. Include all figures and references.",
        model=model, work_dir=work_dir,
        api_key=api_key, base_url=base_url, provider=provider,
        max_continuations=10,
    )
    _accum(assembly_result)

    if assembly_result.success:
        yield TextUpdate(content="  [Assembly] Paper written.\n").to_dict()
    else:
        yield TextUpdate(content=f"  [Assembly] WARNING: {assembly_result.error}\n").to_dict()

    # Phase 4: Review
    yield ProgressUpdate(message="[Phase 4/4] Compiling and reviewing...", stage="compilation").to_dict()

    review_prompt = _REVIEW_PROMPT.format(
        output_dir=str(output_dir),
        docx_file=str(docx_file),
    )
    review_result = await _run_sub_agent(
        agent_id="review", agent_role="Review Agent",
        prompt=review_prompt,
        system_prompt="Review the paper document, fix issues, write review documents.",
        model=model, work_dir=work_dir,
        api_key=api_key, base_url=base_url, provider=provider,
        max_continuations=10,
    )
    _accum(review_result)

    if review_result.success:
        yield TextUpdate(content="  [Review] Complete.\n").to_dict()
    else:
        yield TextUpdate(content=f"  [Review] WARNING: {review_result.error}\n").to_dict()

    total_duration = time.time() - total_start
    yield ProgressUpdate(
        message=f"Multi-agent generation complete in {total_duration:.0f}s",
        stage="complete",
    ).to_dict()
