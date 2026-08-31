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
- **科研工作平台运行时** — SQLite WAL durable tasks、断线事件回放、DAG 节点指标、进程重启后的精确续跑与项目隔离
- **通用 Agent 工作流** — `AgentRole` / `WorkflowRegistry` 支持论文流水线、研究问题冲刺和可复现数据分析，任务页可切换工作流
- **项目资料库** — PDF/DOCX/Markdown/TXT/BibTeX 导入，keyword/semantic/hybrid 检索，页码、片段和哈希锚点可追溯
- **产物审计与恢复** — Agent、脚本和 Python 间接写入均有版本 diff，可从变更页恢复；通用工作流节点保存检查点
- **Web console（Claude 式现代界面，浅/深双主题）** — React 18 + TypeScript + Vite +
  Tailwind v4 构建的前端（源码 `frontend/`，产物直出 `research_assistant/web/static/`）：
  stage timeline, live activity & LLM output stream, real-time budget gauges,
  mid-run steer injection, tool approval cards, run history with one-click resume
  (ArtifactStore checkpointing), events.jsonl audit timeline, paper library with
  zip export; GFM 表格 + KaTeX 公式 + 代码高亮；归约器等纯函数层由 vitest 覆盖
- **会话工作台 + 桌面壳** — chat-first「会话」视图（`/ws/chat` 直连 agent 循环：流式
  文本、内联工具/文件卡片、审批卡与 steer 注入）+ 工作区文件树浏览与泛化文件预览；
  `pip install 'research-assistant[desktop]'` 后用 `research-assistant-desktop` 选一个
  文件夹即可在原生窗口中开工（pywebview，零 node）
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
`RA_PERMISSION_MODE` (`deny_dangerous` default, `off` to disable dangerous-command
blocking), `RA_REPEAT_TOOL_LIMIT` (deny the Nth identical tool call; default 3,
0 = off), `RA_APPROVAL_MODE` (`interactive` enables CLI y/N approval for hooks
that escalate with ask; default off), `ANTHROPIC_PROMPT_CACHE` (`0` disables
cache_control breakpoints), `RA_HEARTBEAT_TIMEOUT`, `RA_AUTO_CONTINUE`,
`RA_MODEL_FAST` / `RA_MODEL_STRONG` (optional role-based model routing).
Wire protocol (run.json / events.jsonl / HookVerdict / approval flow) is
specified in [`docs/protocol.md`](docs/protocol.md).

**Security boundary (read before extending tools).** The workspace fence
(`core.safe_resolve`) covers the `file_ops` tools (read/write/edit/glob/grep)
and `apply_patch` — their path arguments are resolved and verified against the
sandbox root, and Windows reserved device names / NTFS alternate data streams
are rejected (`file_ops._reject_windows_hazard`). The fence does **not** cover
`bash` and `run_python`: these validate only the `cwd` landing spot, not the
command/code text — a model-emitted `cmd /c echo x > C:\...` can write outside
the workspace by design, because a research assistant must be able to run real
scripts. Mitigations are layered, not substituted: `RA_PERMISSION_MODE`
blocks catastrophic commands on the executable surface (`bash`/`run_python`
payloads and MCP extension arguments; file *content* is deliberately not
scanned so that papers about shell commands are not false-positived), the local
HTTP API requires a one-time startup token (`/api` and `/ws`; static assets are
exempt), and MCP subprocesses inherit a sanitized environment without API keys.
True isolation for the execution tools (container / restricted process) remains
the documented extension point — do not try to fix it inside `safe_resolve`.

## Quick Start

### Prerequisites

- Python 3.10+
- LibreOffice (optional, for .docx → PDF conversion)

### Installation

#### Windows 安装包（普通用户推荐，免 Python 环境）

GitHub Releases 提供 `ResearchAssistant_setup_<版本>.exe`：安装后从开始菜单/桌面启动，
首次运行选择一个工作文件夹即可开工；**模型 API Key 在「设置」页图形化配置**（含测试连接），
无需手写 `.env`。卸载走系统「应用与功能」，用户工作目录数据不受影响。

从源码构建安装包：先 `python build.py`（PyInstaller 打包，默认无控制台窗口、
单原生窗体），再运行 `ISCC packaging\installer.iss` 生成 setup.exe。

#### 从源码安装

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
├── workflows/            # AgentRole、WorkflowRegistry 与通用 DAG 执行器
├── runtime/              # SQLite WAL durable tasks、研究对象图、租约队列和任务指标
├── context/              # 项目资料库与 hybrid retrieval
├── artifacts/            # 产物变更版本、diff 和恢复
├── config.py            # Environment + model configuration
├── core.py              # File routing, skill setup
├── models.py            # Data models (PaperResult, TokenUsage, etc.)
├── retry.py             # Retry, heartbeat, error classification
└── utils.py             # Paper scanning, citation counting
```

工作区级平台状态位于 `.ra/platform.sqlite3` 和 `.ra/sources.sqlite3`；论文产物仍位于
`writing_outputs/`，通用工作流节点检查点位于各任务目录的 `.ra/workflow/`。浏览器关闭或
切换页面不会取消后台任务，任务页可重新观察或精确续跑。进入“研究工作台”可维护
研究问题、假设、主张、证据、决策和 provenance；`/api/scheduler/jobs` 提供可恢复的
后台队列，适合定时/批量实验。Web 宿主会自动执行内置和已校验的项目工作流，默认最多
并行 2 个队列任务（可用 `RA_SCHEDULER_CONCURRENCY` 调整）；任务产物会自动进入审阅中心，
并保留 SHA-256、版本、质量门禁和 provenance 关联。

### 科研操作系统工作台

项目首页现在围绕四个科研对象组织工作：Project、Agent Task、Evidence Graph 和 Artifact
Review。任务会自动生成 Thread/Turn/Agent Item、ResearchRun 与 provenance；资料、主张、
分析运行和论文产物可以互相追溯。`/artifacts` 提供文本/PDF/图片预览、版本 diff、门禁详情和
“要求 Agent 修改”；`/analysis` 支持运行比较、后台复现和挂接主张；`/api/project/export`
导出不含密钥和内部缓存的完整研究包，`/api/project/import?conflict=skip|overwrite|rename` 可安全合并回项目并返回文件冲突清单。
项目首页提供 Ctrl/Cmd+K 全局搜索；任务详情提供 Agent 角色、状态、耗时和错误隔离面板；审批请求会进入持久化收件箱。
来源删除会自动为关联主张写入 source_integrity 风险，Citation/Doc/复现门禁失败的产物不能被接受为 final。

常用接口：

- `GET /api/project/home`：项目摘要、活跃任务、风险、通知、资源消耗；
- `GET /api/artifacts/reviews/{id}/preview|diff`：产物 Inspector；
- `POST /api/analysis/runs/{id}/rerun`：按脚本/输入/参数创建复现运行；
- `POST /api/tasks/{task_id}/steps/{step_id}/skip|takeover`：人工控制工作流节点。
- `GET /api/tasks/{task_id}/agents`：任务 Agent roster、角色、状态和耗时；
- `GET /api/approvals` / `POST /api/approvals/{id}/resolve`：持久化审批收件箱；
- `GET /api/project/search?q=...`：跨线程、任务、资料、主张和产物搜索。
- `GET /api/project/activity?after=...`：项目统一活动流；
- `GET /api/agent-runs?task_id=...`：持久化 AgentRun 的角色、预算、输出和状态；
- `GET /api/notifications`：通知中心；`python scripts/perf_research_os.py`：合成性能验收。

当前科研操作系统 beta 主流程已通过真实浏览器 E2E；发布前持续验收项目包括合成性能基准、
真实模型长任务和目标机打包运行。审批收件箱、Agent roster 和质量风险回写已纳入主流程。

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
