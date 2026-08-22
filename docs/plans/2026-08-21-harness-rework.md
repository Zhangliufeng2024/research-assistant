# Research Assistant Harness 改造计划

> **For agentic workers:** 本计划由多 agent 并行执行。任务清单见仓库 Task List；每完成一项需 pytest 全绿后提交。

**Goal:** 为 research-assistant 补上缺失的**机制层**——状态机、质量门（gate）、Hook 系统、上下文管理、评测基准——使长任务从"提示词纪律"变为"代码强制"。

**Architecture:** 在现有自研 agent loop 之上加一个 Kernel 层（事件总线 + 预算守卫 + 取消），将编排重构为显式 Pipeline 状态机（产物落盘 + 断点续跑 + 质量门打回），外部调用全部接入结构化错误分类。宿主（CLI/Web）只是 Kernel 的订阅者。

**Tech Stack:** Python 3.10+ / httpx / asyncio / python-docx / pytest-asyncio / ruff / GitHub Actions。

---

## 0. 参考框架与借鉴对照

> 说明：撰写时 Parallel API 欠费（402）、WebSearch 区域受限（403），以下基于训练知识中的开源实现，未做实时核实；DeepSeek 未公开名为 "harness" 的独立仓库，此处借鉴其"可验证奖励/验证器在环"思想并如实标注。

| 来源机制 | 原理 | 本项目落点 |
|---|---|---|
| OpenAI Codex CLI：rollout 会话 JSONL + resume | 每个事件追加写盘，重启后重放恢复 | `session/store.py`（run.json + events.jsonl） |
| Codex CLI：sandbox/approval 分级 | read-only / workspace-write / full-auto | 权限 Hook 默认策略（P6 骨架） |
| Codex CLI：notify 生命周期钩子 | 宿主程序订阅 agent 生命周期事件 | `kernel/events.py` HookBus |
| Claude Code：PreToolUse/PostToolUse hooks | hook 可放行/拒绝工具调用 | 同一协议，`PRE_TOOL_USE` 返回 `HookVerdict` |
| Claude Code：auto-compaction | 历史超阈值→摘要压缩，保留近端 verbatim | `kernel/context.py` |
| Claude Code：工具结果外置 | 大输出落盘为文件+预览引用 | `kernel/context.py: externalize_tool_result` |
| DeepSeek（思想）：verifier-in-the-loop | 用可验证结果作为终止/奖励信号 | `gates/` 质量门 + `[TASK_COMPLETE]` 门控 |
| 业界通用：结构化错误分类 | 按 status code/body 分类而非字符串匹配 | `llm/errors.py` |

## 1. 目标架构

```
┌────────────── 宿主层 ──────────────┐
│  cli.py        web/(ws, routes)    │   ← 只做 IO 与订阅
├───────────────────────────────────┤
│  api.generate_paper (async gen)    │   ← 兼容层，透传 cancel/resume/budget
├──────── Pipeline 状态机 ──────────┤
│  pipeline/runner.py  ←— 状态机：    │
│   PLAN→RESEARCH∥→FIGURES∥→         │
│   ASSEMBLE→GATES→(REVISION≤3)→DONE │
│  pipeline/artifacts.py (sha256清单) │
├──────── Kernel 层 ────────────────┤
│  agent.run_agent(RunConfig)        │
│  kernel/events.py    Hook 总线      │
│  kernel/budget.py    预算硬闸门     │
│  kernel/context.py   外置+压缩      │
├──────── 基础设施 ─────────────────┤
│  llm/errors.py  结构化错误分类       │
│  session/store.py run.json+事件日志 │
│  gates/         引文门/文档门       │
│  eval/          黄金任务回归        │
└───────────────────────────────────┘
```

### 目标目录（新增部分）

```
research_assistant/
├── kernel/
│   ├── __init__.py
│   ├── events.py        # EventKind / AgentEvent / HookBus / HookVerdict
│   ├── budget.py        # BudgetLimits / BudgetGuard / 价格表 / BudgetExceededError
│   └── context.py       # externalize_tool_result / maybe_compact / token 估算
├── session/
│   ├── __init__.py
│   └── store.py         # SessionStore: run.json 状态机 + events.jsonl
├── gates/
│   ├── __init__.py
│   ├── base.py          # Gate / GateResult / GateReport
│   ├── citation_gate.py # unverified==0 才放行
│   └── doc_gate.py      # 章节/图/字数/占位符检查
├── pipeline/
│   ├── __init__.py
│   ├── artifacts.py     # ArtifactStore（内容寻址、跳过已完成阶段）
│   └── runner.py        # run_pipeline()：状态机执行器
└── eval/
    ├── __init__.py
    ├── metrics.py       # 从产物+门报告计算指标
    └── runner.py        # python -m research_assistant.eval.runner <task.yaml>
eval/golden_tasks/*.yaml
```

## 2. 五大机制设计

### M1 状态机（Pipeline + Session）
- 每个 run 有 `run.json`：`{schema_version, session_id, query, model, state:{stage,status}, stages:{name:{status,artifacts}}, budget, usage}`；
- 每个阶段产物落盘为 typed artifact 并记入 `manifest`（key/path/sha256/stage）；
- Runner 按依赖拓扑执行；**已存在且 sha256 校验通过的产物直接跳过** → 天然断点续跑；
- 进程崩溃后 `--resume <dir>` 从最后完成的阶段继续；删除 cli/api 中所有 mtime 启发式目录猜测。

### M2 Gate（质量门）
- `GateResult{name, passed, severity: blocking|warn, details}`；
- **引文门**：调 citation_verify 编程接口，blocking 条件 = `unverified==0 且 pass_rate≥0.9`；
- **文档门**：plan 中章节齐全、正文引用的图文件存在、字数 ≥ 目标×0.8、无 TODO/placeholder；
- ASSEMBLE 完成后必须过门；不过则注入 gate 报告进入 REVISION 阶段（≤3 轮）；
- `[TASK_COMPLETE]` 只有全部门通过才被 loop 接受为终止信号，否则剥离标记并注入打回原因。

### M3 Hook（事件总线 + 预算 + 权限挂点）
- `EventKind`: RUN_START/TURN_START/LLM_REQUEST/LLM_RESPONSE/PRE_TOOL_USE/TOOL_START/TOOL_END/STEER_INJECTED/BUDGET_WARNING/BUDGET_EXCEEDED/ERROR/RUN_END；
- `PRE_TOOL_USE` hook 返回 `HookVerdict(allowed, reason)`，拒绝时以 `[DENIED by policy]` 作为工具结果回给模型；
- `BudgetGuard`：max_tokens/max_cost_usd/max_turns/max_wall_seconds（env: RA_MAX_COST_USD 等）；80% 触发 BUDGET_WARNING，超限抛 `BudgetExceededError` 由 loop 优雅收尾（保存状态后停止，不中途损毁产物）；
- 权限系统（P6 完整版）未来即是一个内置 PRE_TOOL_USE hook——本次先落默认策略骨架（危险 bash 命令模式拒绝表）。

### M4 上下文管理
- **外置**：工具结果 >4000 字符 → 写 `.ra/tool_outputs/<turn>_<tool>.txt`，消息中只留前 800 字符预览 + 文件指针；
- **压缩**：上次响应 `usage.input_tokens` > 模型窗口×0.7 时触发；保留最近 12 条消息 verbatim（在 tool 配对边界切割），更早区间用廉价 LLM 调用生成结构化摘要（DECISIONS/FACTS/FILES/TODO）替换；
- WRITER.md 中虚假的"自动压缩"承诺改为如实描述。

### M5 评测
- 黄金任务 YAML：query/期望章节数/min_citations/citation_pass_rate/min_words/budget_usd；
- runner 跑完从产物 + `gates_report.json` 提取指标，产出 `eval_results/<ts>.{json,md}`；
- CI 手动触发 job（需 secret LLM_API_KEY），作为后续改 prompt/换模型的回归基线。

## 3. 结构化错误分类（llm/errors.py）

- 分类依据：HTTP 状态码 + provider 错误体 `error.type/code` + `Retry-After` 头；
- 类型：`NetworkError(R)` `RateLimitError(R)` `OverloadedError(R)` `ServerError(R)` `AuthError` `BadRequestError` `ContextLimitError` `ModelConfigError` `HeartbeatTimeoutError(R)`（R=retryable）；
- `retry._is_retryable` 改为优先读 `LLMError.retryable`；旧关键字匹配降级为兜底；
- `retry.py` 对 `ContextLimitError/ModelConfigError/HeartbeatTimeoutError` 做兼容 re-export，cli/api 零改动；
- 心跳语义修正：心跳=流式活动间隔（on_activity 回调），不再是整次请求总时长——健康的长流式响应不再被误杀。

## 4. Agent Loop 升级（agent.py）

```python
@dataclass
class RunConfig:
    max_turns: int = DEFAULT_MAX_TURNS
    auto_continue: bool = True
    max_continuations: int = DEFAULT_MAX_CONTINUATIONS
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    budget: Optional[BudgetGuard] = None
    hooks: Optional[HookBus] = None
    cancel_event: Optional[asyncio.Event] = None
    compaction: bool = True
```

- 保留现有 kwargs 兼容签名，新增 `config` 参数；
- 每 turn 前：cancel 检查 → budget.check()（超限→BUDGET_EXCEEDED→优雅 break）→ steer 注入；
- 工具调用前 emit PRE_TOOL_USE（可拦截）；
- 心跳改为活动看门狗（客户端 on_activity 喂狗）；
- `_llm_call_with_retry` 不再捕获 BaseException，CancelledError 直通。

## 5. Pipeline 阶段定义

| Stage | 输入 | 输出 artifact | 并行 | 失败处理 |
|---|---|---|---|---|
| PLAN | query | plan.json | - | 终止 |
| RESEARCH | plan.json | sources/bib_*.bib, summary_*.md | ∥ 按节，隔离子目录 work/sections/<n>/ | 单节失败不阻塞，标记 partial |
| FIGURES | plan.json | figures/*.png | ∥ | 同上 |
| ASSEMBLE | 全部上述 | drafts/v1_draft.docx, references.bib | - | 重试 1 次 |
| GATES | docx+bib | gates_report.json | - | 不过→REVISION |
| REVISION | gate 报告 | 新版 docx | - | ≤3 轮后仍不过→partial 收尾 |
| FINALIZE | 通过的 docx | final/manuscript.docx, SUMMARY.md | - | 终止 |

## 6. 阶段路线与验收

| # | 内容 | 验收标准 |
|---|---|---|
| P0 | 卫生+CI+错误分类 | ruff 可运行；pytest 绿；429/529/Retry-After 单测通过 |
| P1 | HookBus+Budget+取消+心跳 | mock 测试：hook 拦截工具、预算超限优雅停、取消即时生效 |
| P2 | 外置+压缩 | 长工具结果落盘且对话含指针；模拟超窗触发压缩且 tool 配对完整 |
| P3 | Session/run.json+resume | kill -9 后 --resume 跳过已完成阶段（sha256 命中） |
| P4 | Pipeline 状态机 | mock LLM 全流程跑通；单节失败不影响整体；gate 打回修订路径有测试 |
| P5 | Gates | 伪引文 bib 被拒；缺图文档被拒 |
| P6 | Eval 骨架 | 3 个黄金任务 YAML + metrics 单测（离线 fixture） |
| P7 | Web/CLI 集成 | ws 停止端点；--resume 参数；全量 pytest 绿 |

**本次交付范围：P0–P7 全部。** 明确推迟（记录于 §8）：真沙箱执行隔离、Anthropic prompt caching、skills 知识包路由、MCP、分发更新通道。

## 7. 兼容性承诺

- `generate_paper()` 签名只增不改；`orchestrator.run_orchestrated_generation` 保留可用；
- `retry.py` 异常名全部可继续 import；
- 现有测试 `tests/test_agent.py` 等不改断言仍须通过（新参数均可选）；
- WRITER.md 仅做事实性修正（压缩承诺、[TASK_COMPLETE] 门控说明），不重写领域规则。

## 8. 风险登记

| 风险 | 缓解 |
|---|---|
| 压缩破坏 tool_use/tool_result 配对导致 API 400 | 切割点只在"非配对边界"处；单测覆盖配对完整性 |
| Windows 无内核级网络沙箱 | 本次只做权限默认拒绝表 + 文档声明限制，真隔离留待 WSL/Docker 方案 |
| 预算价格表过期 | unknown 模型按 0 计价并 BUDGET_WARNING 提示 |
| 多节并行写共享目录冲突 | 每节独立 work/sections/<name>/ 子工作区 |
| 评测烧钱 | 黄金任务预算上限字段 + CI 手动触发 |

## 9. 自审结论

- 五大机制（状态机/gate/hook/上下文/评测）均有对应模块与测试任务 ✓
- 兼容层（retry re-export、orchestrator 保留、kwargs 兼容）已列入验收 ✓
- 已知简化：compaction 摘要质量依赖模型、Windows 沙箱非目标，均已登记风险表 ✓
