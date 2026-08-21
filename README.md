# Research Assistant

AI-powered research and writing assistant that combines deep research with publication-ready document generation. Uses a custom agentic loop with `httpx` — no SDK dependencies. Supports both **Anthropic Messages API** and **any OpenAI-compatible API** (DeepSeek, Qwen, GPT, local models, etc.).

**Domains:** Civil & Structural Engineering, Environmental & Energy Engineering, AI/ML for Engineering, Computer Science, and interdisciplinary research.

## Features

- **Automated paper generation** — full IMRaD structure with Word .docx output via PaperBuilder
- **Code sandbox** — `run_python` tool lets the agent write and execute Python code for document creation, data analysis, and figure generation
- **Dual LLM provider support** — Anthropic or any OpenAI-compatible endpoint, user-configurable
- **Custom agentic loop** — no SDK dependencies; lightweight `httpx`-based implementation with tool use, auto-continuation, retry, and heartbeat timeout
- **Real citation lookup** — queries Semantic Scholar, OpenAlex, Perplexity, and Parallel Web; zero tolerance for fabricated references
- **Figure generation** — schematics, data plots, AI-generated images via NVIDIA NIM (free) or any OpenAI-compatible image API
- **Document review** — reads generated .docx to verify content completeness; optional PDF conversion via LibreOffice
- **Multi-agent mode** — resumable pipeline state machine: PLAN → RESEARCH∥ → FIGURES∥ → ASSEMBLE → GATES → REVISION → FINALIZE
- **26 specialized skills** — from scientific writing and venue templates to LCA/carbon analysis and infographics
- **Built-in tools** — read_file, write_file, edit_file, bash, glob_files, grep_search, run_python
- **Programmatic API** — async generator interface with streaming progress updates

## Architecture: The Mechanism Layer

Quality policies are enforced by code, not just prompts:

| Mechanism | Module | What it guarantees |
|---|---|---|
| **State machine** | `pipeline/` + `session/` | Every stage writes sha256-addressed artifacts (`manifest.json`) and state (`run.json`) — a crashed run resumes where it left off via `resume` (CLI) or re-invocation; no mtime guessing |
| **Quality gates** | `gates/` | `CitationGate` (unverified citations block finalization) and `DocGate` (sections present, figures exist, no placeholders, word floor) must pass before `final/manuscript.docx` is written; failures trigger bounded revision rounds (≤3) with the gate report injected |
| **Hook system** | `kernel/events.py` | Lifecycle event bus; `PRE_TOOL_USE` hooks can deny tool calls; budget guard and permission policies are hooks |
| **Context management** | `kernel/context.py` | Oversized tool results are externalized to `.ra/tool_outputs/` with a preview pointer; history is compacted near the window limit with tool-call-pairing-safe cut points |
| **Budget & cancellation** | `kernel/budget.py` + `RunConfig.cancel_event` | Hard caps on cost/tokens/turns/wall-clock (`RA_MAX_COST_USD`, …) stop runs gracefully; web `POST /api/tasks/{id}/stop` cancels mid-run |
| **Structured errors** | `llm/errors.py` | Errors classified by status code/body/`Retry-After` — no substring guessing; silence-based heartbeat never kills healthy slow streams |
| **Eval harness** | `eval/` | Golden tasks (`eval/golden_tasks/*.yaml`) run headless through the pipeline; metrics (citation pass rate, word count, figures, cost) computed offline from artifacts for regression testing |

Key environment variables: `RA_MAX_COST_USD`, `RA_MAX_TOKENS`, `RA_MAX_TURNS`,
`RA_MAX_WALL_SECONDS`, `RA_PIPELINE` (multi-agent implementation switch),
`RA_HEARTBEAT_TIMEOUT`, `RA_AUTO_CONTINUE`.

## Quick Start

### Prerequisites

- Python 3.10+
- LibreOffice (optional, for .docx → PDF conversion)

### Installation

```bash
# Clone the repository
git clone <repo-url> && cd research-assistant

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

### Configuration

```bash
cp .env.example .env
# Edit .env and add your API keys
```

**Writing model** (core agentic loop — decoupled from skill scripts):

| Key | Purpose | Required |
|-----|---------|----------|
| `LLM_API_KEY` | LLM API key (Anthropic or OpenAI-compatible) | **Yes** |
| `LLM_PROVIDER` | `"anthropic"` or `"openai"` (auto-detected from key if not set) | No |
| `LLM_BASE_URL` | Custom API endpoint (e.g. `https://api.deepseek.com`) | No |
| `LLM_MODEL` | Model name (e.g. `deepseek-chat`, `gpt-4o`) | No |

**Image generation** (skill scripts — decoupled from writing model):

| Key | Purpose | Required |
|-----|---------|----------|
| `IMAGE_API_KEY` | Image generation API key (`nvapi-*` for NVIDIA NIM, else OpenAI-compatible) | Optional |
| `IMAGE_BASE_URL` | Image generation endpoint (default: `https://openrouter.ai/api/v1`) | Optional |
| `IMAGE_MODEL` | Image generation model (default: `agnes-2.0-flash`) | Optional |
| `IMAGE_REVIEW_MODEL` | Visual quality review model (default: `agnes-2.0-flash`) | Optional |

**Search & research:**

| Key | Purpose | Required |
|-----|---------|----------|
| `PARALLEL_API_KEY` | Web search and deep research ([parallel.ai](https://www.parallel.ai/)) | Recommended |
| `SEMANTIC_SCHOLAR_API_KEY` | Academic paper metadata | Optional |
| `TAVILY_API_KEY` | Market data and news search | Optional |

**Provider auto-detection:** `LLM_PROVIDER` is inferred from the API key format — keys starting with `sk-ant-` use Anthropic, all others use OpenAI-compatible. Image generation auto-detects from `IMAGE_API_KEY`: `nvapi-*` keys route to NVIDIA NIM, all others use OpenAI-compatible chat/completions.

### Usage

#### CLI

```bash
research-assistant
```

```
> Create a NeurIPS paper on transformer attention mechanisms
> Write a literature review on physics-informed neural networks
> Create an ASCE journal paper on seismic fragility analysis
```

#### Python API

```python
import asyncio
from research_assistant import generate_paper

async def main():
    async for update in generate_paper(
        "Create a paper on structural health monitoring with deep learning",
        track_token_usage=True,
    ):
        if update["type"] == "text":
            print(update["content"], end="", flush=True)
        elif update["type"] == "progress":
            print(f"\n[{update['stage']}] {update['message']}")
        elif update["type"] == "result":
            print(f"\nDocument: {update['files'].get('docx_final') or update['files']['pdf_final']}")

asyncio.run(main())
```

**Key parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `model` | `None` | Override model (e.g. `"deepseek-chat"`, `"gpt-4o"`) |
| `provider` | `None` | Override provider (`"anthropic"` or `"openai"`) |
| `base_url` | `None` | Override API base URL |
| `multi_agent` | `False` | Enable parallel agent orchestration |
| `data_files` | `None` | List of file paths to include as context |
| `track_token_usage` | `False` | Include token usage in the final result |

## Architecture

```
research_assistant/
├── llm/                 # LLM abstraction layer
│   ├── base.py          # Abstract LLMClient, LLMResponse, ToolCall
│   ├── anthropic.py     # Anthropic Messages API (httpx)
│   ├── openai_compat.py # OpenAI Chat Completions (httpx)
│   └── factory.py       # Auto-detect provider, create client
├── tools/               # Built-in tool implementations
│   ├── registry.py      # 7 tool schemas + dispatch
│   ├── file_ops.py      # read, write, edit, glob, grep
│   ├── bash.py          # Shell command execution
│   └── python_exec.py   # Python code sandbox (run_python)
├── agent.py             # Custom agentic loop (tool use cycle)
├── api.py               # Async generator API
├── cli.py               # Interactive CLI
├── docgen.py            # PaperBuilder (.docx generation) + BibTeX parser
├── orchestrator.py      # Multi-agent orchestration (4 phases)
├── config.py            # Environment + model configuration
├── core.py              # File routing, skill setup
├── models.py            # Data models (PaperResult, TokenUsage, etc.)
├── retry.py             # Retry, heartbeat, error classification
└── utils.py             # Paper scanning, citation counting
```

**No SDK dependencies.** The agentic loop is implemented directly with `httpx` HTTP calls. The `llm/` layer normalizes Anthropic and OpenAI wire protocols into a unified interface. Tools are executed locally in-process.

## Output Structure

Each run creates a self-contained directory:

```
writing_outputs/YYYYMMDD_HHMMSS_<description>/
├── progress.md          # Real-time progress log
├── SUMMARY.md           # Project summary and file listing
├── PEER_REVIEW.md       # Automated peer review
├── drafts/              # v1_draft.docx, v2_draft.docx, ...
├── final/               # manuscript.docx, manuscript.pdf (optional)
├── references/          # references.bib
├── figures/             # Generated figures and schematics
├── data/                # Input data files (CSV, JSON, etc.)
└── sources/             # All research results (audit trail)
```

## Skills

| Category | Skills |
|----------|--------|
| **Writing & Review** | scientific-writing, peer-review, literature-review, hypothesis-generation, scientific-critical-thinking, scholar-evaluation |
| **Venue & Citation** | venue-templates, citation-management, research-lookup |
| **Visuals** | figure-generation, scientific-schematics, generate-image, nvidia-image-gen, infographics, scientific-slides |
| **Documents** | docx, pdf, latex-posters, pptx-posters, paper-2-web, markitdown, document-skills |
| **Domain-Specific** | lca-carbon, research-grants, market-research-reports |
| **Infrastructure** | parallel-web, frontend-design |

## Multi-Agent Mode

When enabled, the orchestrator runs 4 phases:

1. **Planner** — decomposes the request into sections and figures
2. **Research + Figure agents** — N research agents + M figure agents run concurrently
3. **Assembly agent** — writes the complete .docx paper via PaperBuilder from gathered materials
4. **Review agent** — verifies document content, fixes issues, writes peer review

Enable via CLI (`multi-agent on`) or API (`multi_agent=True`) or environment (`RA_MULTI_AGENT=true`).

## Data File Workflow

Place files in the `data/` folder before running the CLI. They are auto-classified and copied:

| File Type | Destination | Behavior |
|-----------|-------------|----------|
| `.tex` | `drafts/` | Editing mode — modifies existing manuscript |
| `.png`, `.jpg`, `.svg` | `figures/` | Available as figures in the paper |
| `.csv`, `.json`, `.xlsx` | `data/` | Analyzed and integrated into results |
| `.md`, `.docx`, `.pdf` | `sources/` | Used as reference context |

## Dependencies

Runtime dependencies (minimal):
- `httpx` — async HTTP client for LLM API calls
- `python-dotenv` — environment variable loading
- `python-docx` — Word document generation (PaperBuilder)
- `requests` — used by skill scripts
- `pymupdf` — PDF to image conversion

No SDK dependencies — pure `httpx` HTTP calls.

## Acknowledgments

This project was inspired by and built upon [claude-scientific-writer](https://github.com/K-Dense-AI/claude-scientific-writer) by K-Dense-AI. We sincerely thank the original authors for their pioneering work in AI-assisted scientific writing.

## License

MIT
