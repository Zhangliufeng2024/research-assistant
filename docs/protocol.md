# Research Assistant Harness 协议规格

> 版本：schema_version = **1** · 更新日期：2026-08-23
> 风格参照 `openai/codex` 的 `codex-rs/docs/protocol_v1.md`。
> 本文描述的每个字段与枚举值均以仓库源码为准：`session/store.py`、`kernel/events.py`、`kernel/approval.py`、`kernel/guards.py`、`pipeline/artifacts.py`、`tools/exec_provider.py`。

## 1. 概述

三层架构：

```
宿主层      cli.py / web/(ws,routes)            只做 IO 与订阅
Pipeline    pipeline/runner.py                  状态机编排 + 质量门
Kernel      agent.run_agent(RunConfig)          循环 + Hook/预算/取消/上下文
```

三条设计原则（来源见括号）：

1. **模型可见即已记录**（借鉴 DeepSeek Harness）：凡进入模型请求的消息必须镜像到会话日志，循环用长度账本校验违约；
2. **质量门强制终止**（verifier-in-the-loop）：`final/manuscript.docx` 的写入被引文门/文档门阻断，不依赖模型自觉；
3. **预算硬闸门**：token/$/轮数/时长任一超限即优雅停机，状态先落盘。

## 2. run.json 规范

位置：`<paper_dir>/run.json`；由 `SessionStore` 独占读写；损坏时按全新状态容错重建（产物仍可经 manifest 恢复）。

```jsonc
{
  "schema_version": 1,
  "session_id": "<run_dir 名称或 uuid>",
  "query": "...", "model": "...", "mode": "pipeline | single | chat",
  "stage": "<最后活动的阶段名>",
  "status": "running | complete | failed | cancelled",
  // R12（B4）：仅 chat 会话写入——相对工作区根的产物目录（"outputs/<sid>"）。
  // WS 连接时创建并落盘；旧会话/任务运行缺省为 ""，消费方按 null 处理。
  "outputs_dir": "outputs/<sid>",
  "stages": {
    "<name>": {
      "status": "pending | running | done | failed | skipped | partial",
      "artifacts": ["<artifact key>"],
      "error": "", "started_at": 0.0, "finished_at": 0.0
    }
  },
  "budget": { /* BudgetGuard.snapshot() */ },
  "usage": {}, "created_at": ..., "updated_at": ...
}
```

Pipeline 固定阶段：`plan → research_figures → assemble → gates → finalize`
（修订轮记为 `revision_<n>` 子代理）。单代理模式只产生 `mode:"single"` 与事件日志，无阶段记录。chat 会话无阶段记录，但带 `outputs_dir`（§10.1、§11）。

## 3. events.jsonl 目录

位置：`<paper_dir>/events.jsonl`，追加式，每行一个 JSON 对象：
`{"ts": <秒,3位小数>, "kind": "<名称>", "data": {...}}`。

| kind | 生产方 | data 字段 | 说明 |
|---|---|---|---|
| `msg_add` | kernel | `seq, role, content(≤20k字符), tool_calls(bool)` | 每条进入对话历史的消息；`seq` 为当前账本下的消息序号 |
| `tool_call` | kernel | `tool, arguments` | 工具调用在执行前登记 |
| `tool_result_rewrite` | kernel | `chars_before, chars_after` | post-execute 改写瀑布替换了结果 |
| `approval` | kernel | `tool, approved, note` | ask 审批的最终决定 |
| `steer` | kernel | `message(≤2000)` | 用户中途注入 |
| `compaction` | kernel | `appended, deleted, summary_chars` | 历史压缩；同时更新长度账本 |
| `invariant_warning` | kernel | `expected, actual` | 见 §3.1 |
| `run_end` | kernel/api | `stop_reason, turns`（kernel）/ `status`（SessionStore.finish） | 运行终止 |
| `stage_<name>` | pipeline | `stop_reason, turns, tokens` | 各阶段子代理结束摘要 |
| `gates` | pipeline | `round, passed` | 每轮质量门结果 |
| `run_start` | api(single) | `query_chars` | 单代理运行开始 |

### 3.1 长度账本不变量（"模型可见即已记录"）

内核维护 `ledger = {appended, deleted}`；**所有**对 `messages` 的增删都经由记账辅助函数完成（压缩通过其返回的 info 记账）。每次 LLM 请求前校验：

```
len(messages) == ledger.appended − ledger.deleted
```

违约时发 `INVARIANT_WARNING` 事件并写 `invariant_warning` 日志，**不中断运行**。这是对 dsh 硬断言的有意放宽：本项目的日志是镜像而非唯一事实源（messages 列表仍是运行时权威），软告警足以捕获未记账突变的回归，又避免遥测故障杀死长任务。

## 4. HookVerdict 契约

```python
@dataclass
class HookVerdict:
    allowed: bool = True   # False => 工具被拒，结果为 "[DENIED by policy] <reason>"
    reason: str = ""
    ask: bool = False      # True => 升级到审批（§5）
```

`PRE_TOOL_USE` 上多个 hook 共存，注册序执行，**首个 deny 或 ask 即短路**。默认挂载顺序：权限策略（`RA_PERMISSION_MODE`，见 §8）→ 重复调用守卫（§4.1）→ 宿主自定义。

### 4.1 RepeatToolCallGuard

同名工具 + 参数规范化 JSON 后哈希相同，视为"同一调用"。连续第 N 次（默认 3）返回 deny，理由中指示模型改变方法；每第 N+1 次放行作为防死锁阀（真正幂等的重试仍可推进）。任何不同调用重置计数。`RA_REPEAT_TOOL_LIMIT=0` 关闭。

### 4.2 结果改写（post-execute）

`TOOL_RESULT_REWRITE` 事件的处理器返回非 None 非 HookVerdict 的字符串即替换模型可见的工具结果（首个生效），在外置化之前执行，因此改写产物同样享受 spill 外置。

## 5. 审批流（allow / deny / ask）

类型：`ToolApprovalRequest{tool_name, arguments, turn, reason}` → `ApprovalDecision{approved, note}`。

**裁决规则（照抄 dsh ctx.approval）**：无 approver、超时（默认 120s）、approver 抛异常 —— 一律 **deny**。拒绝时工具结果文本为 `[DENIED by approval] <note>` 并标记 `is_error`。

### 5.1 CLI 时序（RA_APPROVAL_MODE=interactive）

```
SteerReader(线程) ──行──▶ steer_queue ◀──.
                                        │ y/yes=允许；其他任意内容=拒绝
agent: PRE_TOOL_USE(ask)                │
  └─▶ QueueApprover.printer 打印请求     │
      └─ await queue.get() [≤120s] ─────┘
```

审批应答复用转向（steer）输入通道；应答被 approver 消费后不会再注入对话。

### 5.2 Web 时序

```
ws 服务端                                浏览器
  ├─ send {"type":"approval_request", id, tool, summary} ──▶ 审批卡片
  ├─ await approval_queue.get() [≤120s]                    用户点击 允许/拒绝
  ◀── receive {"action":"approval", id, approved} ◀──────── ws.send
```

连接断开时 pump 任务置位 cancel_event 并向队列投递 None 以解除阻塞的问询（等效拒绝）。

## 5.3 后台任务协议 (/ws/generate)（v3.5+）

生成任务由 `BackgroundTaskHub`（SQLite WAL 持久化）拥有，WebSocket 只是观察者：
关闭浏览器/切换页面**不会取消任务**，任务在服务端继续执行。

### 5.3.1 工作流 DAG

多 Agent 论文任务在创建时还会持久化一份 `task_steps` DAG（节点、依赖、状态和起止时间），
而不只保留文本日志。当前论文工作流为：`plan → {research, figures} → assemble → gates → finalize`。
`GET /api/tasks/{task_id}/plan` 可在断线或刷新后重新取得该图；前端任务页据此显示真实的执行节点。
`GET /api/tasks/{task_id}/metrics` 返回总耗时、节点耗时、关键路径估计和事件数，用于定位性能瓶颈。
此存储层对任意后续研究工作流通用，节点状态由后台 hub 的事件流写入 SQLite。
可用工作流由 `GET /api/workflows` 返回；首帧 `start` 可携带 `workflow_id`，论文工作流
（`paper`）继续使用科研专用流水线，其它声明式工作流由通用 Agent Role 执行器运行。

### 5.3.2 脚本产物版本化

`write_file`/`edit_file` 之外，`run_python` 与 `bash` 也会对其执行产物目录做前后
快照（最多 512 个文件、32 MB，且在工作线程完成）。新增、修改和删除均写入
`.ra/changes/`，并可从「变更」页查看 diff 或恢复。会话/论文任务配置了产物锚点时只
扫描该锚点，不扫描整个工作区；同时，执行工具的 `cwd` 必须位于工作区围栏内。

首帧三选一：

- 启动：`{"action":"start", "query", "multi_agent?", "workflow_id?", "max_cost_usd?", "max_wall_seconds?", "resume_run?"}`
- 观察：`{"action":"observe", "task_id", "after": <seq>}` —— 重连后从 `after` 起回放错过的持久化事件（`GET /api/tasks/{id}/events?after=N` 亦可拉取）。
- 精确续跑：`{"action":"resume_task", "task_id"}` —— 复用 durable task 记录的产物根目录和工作流检查点。

事件帧带单调递增 `seq`；`done` 帧含 `task_id/status`。停止必须显式调用
`POST /api/tasks/{id}/stop`（协作取消）。REST：`GET /api/tasks`、`GET /api/tasks/{id}`、
`GET /api/tasks/{id}/events?after=N`。进程重启时遗留的 running 任务被标记为 `interrupted`；
任务页会保留查询和模式，并提供「重新运行」入口，避免用户因服务重启丢失工作意图。

项目长期指令（设置页「项目长期指令」）经 `PUT /api/project/instructions` 持久化于平台库，
并注入流水线每个子代理的系统提示。`GET /api/workflows` 暴露角色分级和 DAG 描述；
通用工作流节点会把完成结果写入 `.ra/workflow/*.json`，续跑时按节点恢复。

资料库检索：`GET /api/sources/search?q=...&mode=hybrid|keyword|semantic`。默认混合检索
以 FTS5 精确命中为主，并结合离线确定性向量；单次向量扫描有上限，避免大资料库拖慢任务。

产物变更审计：`GET /api/workspace/changes`、`GET /api/workspace/changes/{id}`、
`POST /api/workspace/changes/{id}/restore`（agent 的 write_file/edit_file 均有前后快照，
可一键恢复；bash/run_python 的间接写入也纳入）。

## 5.4 科研对象图与可复现运行（v3.6+）

`.ra/platform.sqlite3` 同时持久化科研对象，而不再只保存任务日志：

- `research_items`：研究问题、假设、目标和笔记，带版本号；
- `claims` / `evidence` / `evidence_links`：主张、资料锚点或产物证据及支持/反驳关系；
- `decisions`：带理由的决策日志；
- `research_runs`：任务/工作流的输入、环境、输出、状态和时间；
- `provenance_edges`：任意对象之间的来源链；
- `job_queue`：带租约、尝试次数和退避时间的持久化后台队列。

每个 `BackgroundTaskHub` 任务创建时自动生成一个 `research_run`，并写入 task → run
provenance 边；任务完成时保存产物目录和最近一次 usage/budget 快照。

所有对象都以 `project_id` 隔离。核心接口为：
`/api/research/overview`、`/api/research/items`、`/api/research/claims`、
`/api/research/evidence`、`/api/research/decisions`、`/api/research/runs`、
`/api/research/provenance`。`overview.uncovered_claims` 是最小证据覆盖门禁，前端
“研究工作台”会直接显示待补证据的主张。`/api/research/quality` 进一步返回主张覆盖、
孤儿证据、失败运行和 `ready_for_synthesis` 门禁结果，可作为增量合并前的质量检查。

调度接口为 `/api/scheduler/jobs`。队列任务由 `DurableScheduler` worker 领取，
使用 SQLite 事务租约防止重复执行；worker 崩溃后过期租约会自动回收，失败任务按
`max_attempts` 与退避时间重试。WebSocket 任务仍可即时启动，队列则适合定时、批量和
无浏览器后台执行。Web 宿主在 lifespan 中注册内置 workflow dispatcher；dispatcher
将队列行转换为 `BackgroundTaskHub` 任务，写回 `job_queue.task_id`，并等待任务结束后
再确认队列完成。payload 可包含 `query`、`model`、`provider`、`output_dir`、
`data_files` 和预算字段，但不得包含 API Key。
单个 scheduler worker 默认最多并行执行 2 个队列任务，可通过
`RA_SCHEDULER_CONCURRENCY`（1–16）调整；Agent 工作流内部仍受
`RA_AGENT_CONCURRENCY` 限制。资源 key 达到并发上限时，任务会延迟回队且不消耗
`max_attempts`，避免正常的资源背压被误记为失败。

## 5.5 统一科研工作空间（v3.7+）

项目默认入口为 `/` 的 Project Home。旧会话页保留在 `/chat`，并新增：

- `/threads`：统一 Thread 列表和 Agent Item 时间线，支持线程分支；
- `/artifacts`：产物版本审阅、接受、拒绝和要求修改；
- `/api/project/home`：项目摘要、活跃任务、线程、质量风险、待审阅产物和决策；
- `/api/project/search`：跨线程、任务、研究对象、决策和产物的项目级搜索；
- `/api/research/evidence-matrix`：主张—证据矩阵；
- `/api/research/quality/items`：可持久化质量风险项；
- `/api/artifacts/reviews`：产物审阅状态和评论。
- `/api/artifacts/reviews/{review_id}`：审阅详情、project-scoped provenance 和质量项；
  `/preview` 返回文本内容或受围栏保护的二进制预览 URL；`/diff` 返回工作区版本 diff；
  `/request-changes` 将审阅意见写入线程 Agent Item 并生成通知。

Durable Task Hub 启动任务时会自动创建兼容 Thread/Turn，并将进度帧映射为 Agent Item；
旧 `/ws/chat`、`/ws/generate` 和 `/api/tasks` 仍是兼容入口，迁移期间不改变既有任务和
论文目录协议。

## 5.6 Supervisor 与可复现分析（v3.8+）

通用工作流 ready 节点由 `AgentSupervisor` 执行，使用 `RA_AGENT_CONCURRENCY` 限制并发，
为每个 Agent 发出 queued/running/complete/failed/cancelled 生命周期事件。事件会进入
统一 Thread 的 Agent Item，同时继续写入旧 task event stream；论文专用 pipeline 的
Citation/Doc Gate 语义不变。工作流节点可声明 `timeout_seconds`；超时只将该 Agent
标记为 failed，并保留其他并行节点的结果。

通用 workflow 可通过 `POST /api/tasks/{task_id}/steps/{step_id}/rerun` 精确重跑节点。
接口创建新的 durable queue job，并在新运行开始前删除目标节点及其下游的 `.ra/workflow`
checkpoint；上游 checkpoint、旧 task、旧 research_run 和旧产物记录保留不变。论文专用
pipeline 和单 Agent 任务暂不支持该接口。

`analysis_runs` 持久化脚本路径与 SHA-256、输入 manifest、参数、运行环境、输出、stdout/
stderr 截断记录和退出码。接口为 `/api/analysis/runs`；前端“分析运行”页支持按输入、
参数、环境和输出审阅，并提供 `/compare`、`/{run_id}/rerun` 和 `/{run_id}/evidence`。
复现会创建新运行并写入 `reproduced_from` provenance，在后台以
`RA_ANALYSIS_INPUTS_JSON`、`RA_ANALYSIS_PARAMETERS_JSON`、`RA_ANALYSIS_OUTPUT_DIR` 环境契约
执行脚本；非零退出会生成 reproducibility quality item。

任务终态会扫描其 `output_dir` 下的用户产物（排除 `.ra`、`.git`、缓存和隐藏文件），在
`artifact_reviews` 写入相对路径、版本、SHA-256、文件大小/类型和 `quality_gates` 摘要。
同一路径 hash 变化会生成下一版本；门禁报告中的失败项会写入 `quality_items`，并通过
provenance 建立 task → artifact_review 边。文件本身不会被复制或移动。

工作流节点人工控制：`POST /api/tasks/{task_id}/steps/{step_id}/skip` 和 `/takeover` 会更新
节点状态并追加人工控制 Agent Item。工具审批事件携带一次性 `request_id`（前端 ApprovalCard
同时展示 agent_id/role）；任务 WebSocket 的 approval 回执必须带同一 id，迟到/错误回执被丢弃。

研究包：`GET /api/project/export` 输出 `research_manifest.json`、`sources.json` 和
`workspace/` 用户产物；`POST /api/project/import?overwrite=false` 校验 ZIP 路径并把 manifest
安全合并到当前 project，默认跳过已有文件。`.env`、`.ra`、VCS、缓存以及 queue worker
内部字段不进入导出包。

运行队列页 `/scheduler` 对应 `/api/scheduler/jobs` 和 `/api/scheduler/triggers`，提供立即
排队和间隔触发入口；内置 `paper`、`research_sprint`、`data_analysis` 和 `single`
工作流会由宿主自动执行，项目保存的工作流定义会先按已注册 Agent role/dependency
校验后再执行。队列 payload 只携带可审计的任务参数，密钥和连接对象保留在进程内。
多个 scheduler 进程共享同一 SQLite 数据库时，通过 `resource_leases` 表原子占用
provider/model 资源槽位；进程崩溃后租约过期自动回收，资源争用不会消耗任务重试次数。

## 6. ArtifactStore（断点续跑）

manifest 位于 `<output_dir>/.ra/artifacts/manifest.json`：

```jsonc
{"artifacts": [{"key","path","sha256","stage","created_at"}]}
```

`is_valid(key)` = 文件存在 且 sha256 与登记一致。Runner 在每阶段开始前检查其产物 keys：全部 valid → 整段跳过（resume）；否则重跑该阶段。删除产物文件即强制重跑对应阶段。

## 7. ExecProvider seam

```python
class ExecProvider(Protocol):
    async def run_bash(self, command: str, timeout: int, cwd: str) -> str: ...
    async def run_python(
        self, code: str, timeout: int, cwd: str,
        *, workspace_root: str | None = None,
    ) -> str: ...
```

`ToolRegistry(exec_provider=None)` 默认装配 `LocalExecProvider`（委托现有本地实现）。替换 provider 即把 bash/run_python 整体迁移到其他执行世界（容器/远程沙箱），工具定义与提示词零改动。扩展点仅此一处，暂无远程实现。

R12 加性扩展：`run_python` 的 `workspace_root=None` 关键字参数由 registry 固定传
`self.work_dir`（§11.3）——冻结执行器用它给子进程注入全局常量 `WS`。自定义 provider
可忽略该参数（签名带 `**kwargs` 或同名默认参即可兼容）。

## 8. 环境变量总表

| 变量 | 默认 | 含义 |
|---|---|---|
| `RA_PIPELINE` | `true` | multi-agent 走 pipeline 状态机（false=旧 orchestrator） |
| `RA_PERMISSION_MODE` | `deny_dangerous` | `off`=关闭危险命令拦截 |
| `RA_REPEAT_TOOL_LIMIT` | `3` | 相同工具调用拒绝阈值；`0`=关闭 |
| `RA_APPROVAL_MODE` | `off` | `interactive`=CLI 启用 ask 审批问询 |
| `ANTHROPIC_PROMPT_CACHE` | `true` | `0`=禁用 cache_control 断点 |
| `RA_MAX_COST_USD` / `RA_MAX_TOKENS` / `RA_MAX_TURNS` / `RA_MAX_WALL_SECONDS` | 无限制 | 预算硬闸门 |
| `RA_HEARTBEAT_TIMEOUT` | `300`s | 流式静默看门狗窗口 |
| `RA_AUTO_CONTINUE` | `true` | 自然停止时是否自动续跑 |
| `LLM_REQUEST_INTERVAL` | `2.0`s | 同一 client 相邻请求最小间隔 |
| `RA_MAX_RETRIES` / `RA_RETRY_BASE_DELAY` | `3` / `5.0`s | 瞬态错误重试参数 |
| `RA_LLM_FIRST_BYTE_TIMEOUT` | `60`s | 模型端点首字节等待；网络偏慢时可调小（前端等待提示文案引用此变量） |
| `RA_ALLOW_SHELL_OPEN` | 关闭 | `"1"` 时 `/api/workspace/open` 才允许调系统文件管理器，否则 403。**桌面壳 main() 自动置 1**（受信本地进程）；纯 web 部署保持默认关闭——前端 dock 按钮 403 时 toast 提示而非隐藏 |
| `RA_FF_<NAME>`（R17） | 各 flag 默认 | 统一 feature flag（`config.feature_flag`）：`1/true/yes/on` 开启；重构灰度专用，新行为先挂 flag 后转默认 |
| `RA_JANITOR_INTERVAL_SECONDS`（R17） | `3600` | Janitor 分层清理的触发间隔（挂 DurableScheduler 主循环）；`0`=关闭 |
| `RA_JANITOR_WARM_DAYS` / `RA_JANITOR_COLD_DAYS`（R17） | `30` / `90` | 温层（超龄标记 archived）/ 冷层（已归档超龄：events.jsonl gzip + 产物 drafts/ 删除）阈值 |
| `RA_JANITOR_CHANGES_CAP_MB` / `RA_JANITOR_EVENTS_ROTATE_MB` / `RA_JANITOR_EVENTS_KEEP` / `RA_JANITOR_TMP_DAYS`（R17） | `500` / `10` / `3` / `7` | .ra/changes LRU 总量上限 / 单会话日志轮转阈值与代数 / tmp 清扫龄期 |
| `RA_PERSIST_THOUGHTS`（R17，预留） | 关闭 | 思考内容是否落盘 events.jsonl；默认不落盘（思考只走 WS 流，历史体积与隐私考虑） |

## 9. 版本化承诺

1. 任何破坏 `run.json` / `events.jsonl` / HookVerdict 语义的改动必须递增 `SCHEMA_VERSION`；
2. 读取端必须容忍未知字段与未知 kind（现实现已满足：`SessionState(**known_only)`、逐行 try-parse）;
3. 新增枚举值/事件 kind 不算破坏性变更（消费方按白名单处理的应忽略未知值）。

## 10. 会话协议 (/ws/chat)（R2；R16 耐久化修订）

> 实现权威：`web/chat.py`；前端消费方：`frontend/src/lib/protocolChat.ts`（reduceChat 纯函数归约）、`frontend/src/stores/chatStore.ts`（WS 生命周期与断线重连 attach 接线）。
> 挂载：同一 router include 两次 —— REST 带 `prefix="/api"`，WS 无前缀落在 `/ws/chat`。
>
> **R16 耐久化**：回合生命周期与连接解耦——断开/刷新只减少观察者计数，运行中的回合继续跑到终态并把回复全路径落盘；重连后发 `attach` 从环形缓冲按 seq 回放错过的帧。旧契约「断连即取消回合」废除。

### 10.1 会话目录与持久化（D2）

每会话一个目录 `<workdir>/.ra/sessions/<YYYYMMDD_HHMMSS_slug>/`：

| 文件 | 角色 |
|---|---|
| `run.json` | SessionStore 状态机；`mode:"chat"`、`status: running/complete/cancelled/failed`、预算快照 |
| `events.jsonl` | kernel 逐条审计镜像（§3 目录），不用于重建 |
| `history.json` | **对话唯一权威**（D2）：`{"schema_version": 1, "messages": [...]}` 归约文本往来；每轮结束整份写回，重启即恢复。条目基形 `{"role": "user"\|"assistant", "content": str}`，R16 起带结构化扩展——user 条目可携带 `attachments:[{name,path}]`（喂内核前才把路径清单拼进正文，权威数据保持结构化），assistant 条目在 cancelled/failed 且有残缺文本时带 `"partial": true`。工具调用明细不入 history |

slug 由可选标题派生（保留 CJK）；同秒重名追加 `_n` 序号。

**产物目录（R12 双轨制）**：chat 会话的工具产物落 `<workdir>/outputs/<sid>/`（与任务
模式的 `writing_outputs/` 分轨）；WS 连接即创建，`run.json.outputs_dir` 记相对路径。
清退（零轮次）与会话删除均**配对删除** `outputs/<sid>`——零轮次 ⇒ 从未执行过工具 ⇒
产物目录不可能含用户数据，配对删除安全；孤儿 outputs 目录（会话目录已不在）惰性无害，
不主动清扫。R16 起该目录下还有 `uploads/` 子目录：multipart 附件上传的落点，send 时
附件引用校验与之同一围栏（见 §10.2 / §10.3）。

### 10.2 REST（挂载于 `/api` 前缀下）

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/api/chat/sessions` | body 可选 `{"title": str}` | `{"id", "created_at"(epoch 秒)}` |
| GET | `/api/chat/sessions` | — | `[{id, title?null, last_message(≤80字), turns(用户消息数), created_at, updated_at, outputs_dir?null}]` 按 updated_at 倒序。列表前先清退**零轮次且 updated_at 距今 > 1h** 的目录（用户消息回合开始前先落盘，零轮次 = 从未收到用户帧，删除不丢内容；§6.4 空会话治理；R12 起配对删 `outputs/<sid>`）。`outputs_dir` 取 run.json，旧会话为 null（恢复期兜底；权威源是 connected 帧，见 §10.3） |
| GET | `/api/chat/sessions/{id}` | — | `{id, messages:[{role,content, attachments?, partial?}...]}`（history.json 全量；R16 起结构化扩展字段透传——user 条目可带 `attachments:[{name,path}]`、残缺回答带 `partial:true`，与 §10.1 落盘口径一致）；未知 404、非法 ID 403 |
| PATCH | `/api/chat/sessions/{id}` | `{"title": str}`（空白/缺失 422，截断 ≤80 字） | `{ok:true, id, title}`；改写 run.json 的 query 字段（SessionStore.state.query），updated_at 原样保留不触发列表跳顶，留 `session_rename` 审计事件；未知 404、非法 ID 403。前端 UI 层对 running 会话拦截改名（回合收尾 store.save() 整份写回会覆盖并发改名） |
| DELETE | `/api/chat/sessions/{id}` | — | `{ok:true}` 删除整个目录。R16 顺序：先落墓碑（此后该会话一切迟到写回被拦截并自删残留）→ 运行中先 close(4002) 通知活跃连接、置位 cancel_event 并精确等回合收尾（上限 8s，超时硬取消兜底）→ rmtree 会话目录并**配对删除** `outputs/<sid>` |
| POST | `/api/chat/sessions/{id}/truncate` | body `{"keep": N}` | `{ok:true, kept, removed}` 把 history.json 截断为前 keep 条（「重新生成 / 编辑重发」的服务端支点：截断后原文重发，重开会被历史回灌的不再是旧答案）；keep 非法/负数 422；**回合运行中 409**（历史正被追加）；未知/墓碑 404、非法 ID 403 |
| PATCH | `/api/chat/sessions/{id}/messages/{index}` | body `{"text": str}` | `{ok:true, index}` 就地改写一条 user 消息（编辑重发第一步；assistant 条目不可改）；非空且 ≤8000 字符（MAX_USER_LENGTH）否则 422、角色非 user 422、序号不存在 404；运行中 409 |
| POST | `/api/chat/sessions/{id}/attachments` | multipart 表单（≥1 个文件字段） | `{"files":[{name,path,size}]}`；文件落 `outputs/<sid>/uploads/`（`<时分秒>_<序号>_` 前缀防撞名 + 文件名消毒：取 basename 剥盘符目录成分、剔除非法字符、Windows 保留设备名降级加前缀）；1MB 流式写盘，单次请求总量超 50MB（UPLOAD_TOTAL_LIMIT）报 413 并清掉半截文件；运行中的回合也允许上传（本轮用不上，下一条消息即可引用） |
| POST | `/api/chat/sessions/{id}/flags`（R17） | body 至少含 `pinned` 或 `archived`（bool；双缺 422） | `{ok:true, session_id, pinned, archived}`；会话标志位持久在 platform.sqlite3 `session_meta` 表（替代旧 localStorage 归档，跨端可见）；部分更新保留另一标志；会话不存在 404、非法 ID 403、无平台库 503 |
| POST | `/api/chat/sessions/{id}/promote`（R17） | body 可选 `{"prompt"?: str, "workflow_id"?: str=single}` | `{ok:true, job_id, workflow_id}`；把最近 ≤20 条对话（总量 ≤6000 字符）打包进任务 query 并入队 scheduler 队列，payload 携 `source_session_id`——任务落库带来源锚点（列表徽标/详情回链的支点）；会话不存在 404、非法 ID 403、无平台库 503 |
| GET | `/api/runs/search`（R17） | query: `q?`, `status?`, `limit?≤200=50`, `offset?=0` | `{total, items:[task...], limit, offset}`；历史运行的标题子串+状态过滤+分页检索（替换前端 slice(0,20) 硬截断）；task 对象含 R17 新增 `source_session_id` 字段（旧任务为 null） |
| GET/PUT | `/api/settings/{key}`（R17） | PUT body `{"value": str}`（缺失 422） | `{key, value}` / `{ok, key, value}`；跨端 UI 设置（如 `ui.verbosity` 显示档位），存 platform.sqlite3 meta 表（`setting.` 前缀） |
| GET | `/api/search`（R17；迭代2 扩展） | query: `q`(必填非空), `scope?=all\|sessions\|tasks\|artifacts`, `limit?=20` | `{sessions:[{id,title,updated_at}], tasks:[task...], artifacts:[{session_id,path,name,ext,size,mtime}]}`；统一检索入口（Ctrl+K 与历史页共用）；artifacts scope 读 platform.sqlite3 artifacts 索引（由 manifest 端点回填） |
| GET | `/api/chat/sessions/{id}/manifest`（迭代2） | — | `{session_id, count, files:[{path,name,ext,size,mtime}]}`；懒重建会话产物清单（mtime 倒序，截 500 条），落盘 `outputs/<sid>/manifest.json` 并整表回填 artifacts 索引（`replace_artifacts`）；删除会话时索引同步清除（`drop_artifacts`，防检索幽灵命中）；会话不存在 404、非法 ID 403 |
| PATCH/DELETE | `/api/scheduler/triggers/{id}`（R17） | PATCH body `{"enabled": bool}`（缺失 422） | PATCH 回触发器对象、DELETE 回 `{ok:true}`；触发器启停与删除（此前 enabled 只读、无删除入口）；跨项目操作一律 404（不存在口径） |

历史治理端点共用一套口径：非法 ID 403、未知/墓碑会话 404；改历史的两个端点（truncate /
messages PATCH）在回合运行中一律 409——附件上传不受此限。

### 10.3 WS 帧 schema

连接：`GET ws://host/ws/chat?session=<id>`；`session` 缺省则新建会话；给出的 id 已被删除时
按同名幂等重建（不卡 UI）；含路径分隔符/盘符的 id 发 `error` 帧并关闭。断连对回合无副作用
（见 §10.4）。

**帧序号 seq（R16）**：回合帧——`text` / `tool_card` / `approval_request` / `usage` /
回合终态的 `error` / `result`——经 `_TurnHandle.next_seq()` 注入自增 `seq` 并登记进环形
缓冲（`FRAME_RING_CAP=4000`，超限丢最旧：丢的只是最老的 usage 快照，不影响语义完整性；
缓冲是 attach 回放的唯一来源）。`seq` **会话内单调**：新建回合句柄时从上一回合句柄
续接计数，不得归零——前端游标与 `attach{after}` 过滤以会话内递增为前提（每回合清零会让
重连后错过的帧被旧游标永久滤掉）。连接级帧**无** `seq`：`connected`、`replay_begin` /
`replay_end` / `replay_empty` 与 dispatch 路径的即时校验 `error`（空消息、空闲 steer 报错等）。

**server → client**

| type | 字段 | 说明 |
|---|---|---|
| `connected` | `session_id`, `outputs_dir` | 握手完成（无 seq），可发消息。带 `outputs_dir`（相对工作区根的产物目录，如 `"outputs/<sid>"`）——**前端产出 dock 的权威源**（REST 列表在工作区切换后会错接到另一工作区的同名目录）；旧会话为 null |
| `text` | `delta`, `seq`[, `channel`] | 流式正文增量；接续最后一个 text 气泡（前端合并）。**R17 起可选 `channel` 字段**：缺省=正文；`"thought"`=模型思考增量（provider 的 thinking/reasoning 流，绝不混入正文与落盘历史）；`"plan"`=planner 直播（/plan 门过程，前端折叠进 L1 过程区）。旧客户端忽略该字段即回落旧语义 |
| `tool_card` | `id`, `tool`, `arguments`, `status: running\|done\|error`, `result_preview`(≤400字), `files:[{path}]`, `seq` | 同 `id` 多次推送按卡合并；`files` 从 write_file/edit_file 的 `file_path` 与 bash/run_python 结果文本的扩展名启发式提取（去重保序，≤8 条） |
| `usage` | `budget`: BudgetGuard.snapshot(), `seq` | 运行期约每 1s 一帧，结束至少一帧（复用 B5 usage_ticks） |
| `approval_request` | `id`, `tool`, `summary`, `agent_id`, `role`, `seq` | PRE_TOOL_USE ask 升级时推送；`id` 为本次问询唯一标识（回执按 id 去重）；`agent_id`/`role` 为多 agent 场景标识（单 agent 空串） |
| `result` | `stop_reason`, `turns`, `seq` | 一轮结束。stop_reason 枚举同 AgentResult（completed/cancelled/budget_exceeded/max_turns/max_continuations）；回合异常收场时为合成的 `"error"`。stop_reason=cancelled/error 时流式文本是残缺回答（与落盘 partial 标记同口径） |
| `error` | `message`[, `seq`][, `traceback`] | 校验失败/配置错误（如缺 API key）为连接级即时帧、无 seq；回合失败的错误帧经发射路径带 seq，网络类错误自动附排查指引文案。**R17 起回合失败帧附可选 `traceback`（截尾 4000 字符）**：L0 只展示 message，堆栈供「调试」档（L2）渲染 |
| `replay_begin` | `last_seq`, `status` | attach 应答头（无 seq）：缓冲内最新 seq 与目标回合当前状态（running\|complete\|failed\|cancelled） |
| （原帧原样补发） | 各回合帧 | 缓冲中 `seq > after` 的帧逐帧补发（快照迭代，边回放边新增安全） |
| `replay_end` | `status`, `last_seq` | 回放结束（无 seq）；status=running 时客户端恢复「思考中」态 |
| `replay_empty` | — | 无可回放回合（既无活动回合也无刚结束句柄）：客户端回落 REST 历史渲染 |

**client → server**

| action | 字段 | 说明 |
|---|---|---|
| `user` | `text`(≤8000), `attachments`?: [{name,path}](≤8) | 触发一轮；空/超长发 `error` 且不启动循环。`attachments` 引用必须是本会话 `outputs/<sid>/uploads/` 围栏内的已上传文件（safe_resolve 校验，绝对路径越界同样拒绝），数量上限 ATTACHMENTS_MAX=8。**运行中收到新的 user 动作按 steer 转交**（截到 MAX_STEER_LENGTH=2000，不另起回合） |
| `approval` | `id`, `approved` | 应答当前问询；服务端按当前问询 id 去重——无活动回合或 id 不符（迟到/伪造/重复）直接忽略，防止残留答案自动应答下一次问询 |
| `steer` | `message`(≤2000) | 运行中注入 steer_queue（内核下一轮首并入 user 消息）。**R16 起空闲期显式报错「当前没有运行中的回合」**——不再静默入队待下轮（幽灵注入不可见）；空/超长同样报 error |
| `stop` | — | 置位活动回合 cancel_event 协作停止本轮（结果帧 stop_reason=cancelled，已流出文本带 partial 落盘）；无活动回合为无害 no-op |
| `attach` | `after`(<最后收到的 seq>) | R16 重连续传入口：服务端回 `replay_begin` → 补发 `seq > after` 的缓冲帧 → `replay_end`；无可回放回合回 `replay_empty`。attach 同时接管观察并撤销孤儿看门狗（§10.4）。**attach 之后同一回合新产生的帧经直播路由继续到达本连接**（发射按 sid 现查当前活跃连接的信箱，不绑死发起回合的 socket）——回放补历史、直播续尾流，两者衔接处由服务端同步段保证不重不漏。冷打开（REST 恢复历史后首次建连）不 attach：REST 历史已含完整旧轮次，整轮回放反而造成重复条目；但「自动重连放弃后用户直接再问」触发的全新连接**必须**带 `after=lastSeq`（lastSeq>0 时）——上一回合离线期的尾流只能由此补齐 |

未知 action/type 均容忍（error 帧 / 忽略），符合 §9 承诺。

### 10.4 生命周期

```
浏览器                                   ws_chat 服务端
  │── GET /ws/chat?session=<id> ──────▶ accept；定位/新建会话目录（连接即建 outputs/<sid>）
  │                                      同会话并发：后连者 close(4001) 踢前者
  │◀── {"connected",session_id,outputs_dir} ─┤ 组装 ToolRegistry(work_dir=工作区根围栏,
  │                                       write_anchor=exec_cwd=outputs/<sid>，§11.2)
  │── {"action":"user","text"} ───────▶ 用户消息先行落盘 → spawn 回合任务 _turn_main
  │◀── text/tool_card/usage…(带 seq)     （立即返回，主循环继续收 steer/approval/
  │◀── {"result",stop_reason,turns}      stop/attach）
  │                                       终态全路径持久化：assistant 条目写回
  │                                       history.json（cancelled/failed 且有文本带
  │                                       partial:true）+ SessionStore.finish(status)
  │── 断开 / 刷新 ────────────────────▶ 仅观察者 -1；回合照跑（「断连即取消」废除）
  │        无人重连时，宽限 RA_CHAT_ORPHAN_GRACE_SECONDS（默认 900s，下限 30s）到期：
  │        先置位 cancel_event 协作停止（内核在安全点正常落盘 partial 文本）→ 再等
  │        ORPHAN_HARD_CANCEL_S=30s 仍未结束才 task.cancel() 硬取消兜底
  │── 重连 GET ?session=<id> ─────────▶ connected 后：
  │── {"action":"attach","after":N} ──▶ replay_begin{last_seq,status}
  │◀── 缓冲中 seq>N 的帧逐帧补发         attach 接管观察、撤销孤儿看门狗
  │◀── {"replay_end",status,last_seq}
```

- **回合终止途径只有三个**：显式 `stop`、删除会话（DELETE 先关 socket 再置位 cancel_event
  并等收尾）、孤儿宽限到期。预算守卫（`RA_MAX_*`）始终是支出上界，宽限只是体验参数；
- **观察者模型**：每条连接至多观察一个活动回合（回合启动或 attach 时 +1，连接退场在
  finally 归还）；计数归零且回合仍在跑才武装看门狗任务，任何 attach 都撤销之——刷新页面
  在宽限内重连是无缝接管；
- **发射路径不感知连接状态**：回合帧先入环形缓冲再按 sid 路由到**当前活跃连接**的出站
  信箱（每连接一个单消费者泵，天然串行化；无连接时静默留待 attach 回放）。路由目标现查
  `_SINKS` 表而非闭包绑死发起回合的 socket——否则重连后 attach 只补得历史快照、其后的
  直播尾流永远发进尸体 socket（前端永久停在「思考中」，对抗性审查抓出的缺陷）。推送失败
  静默，不存在「发送失败 → 同步取任务结果」的窗口（对 InvalidStateError 断连丢史连锁的
  结构性消除）；
- **R16 行为收紧两处**：空闲期 steer 显式报错、审批回执按 id 去重（见 §10.3）。

### 10.5 内核适配说明

- **流式**：run_agent 传入 `on_text` 即走流式路径（on_chunk 逐段回调），故 `text` 帧为真实增量；
- **多轮历史**：run_agent 每轮从全新 messages 起步，无初始历史参数——由模块内
  `_HistoryClient` 包装层补足：检测到本轮首个请求形态（单条 user 消息）时把
  history.json 的归约历史前置拼接（重试同样展开；用量按含历史的真实请求计量）；
- **auto_continue=False**（有意偏离 generate 流程）：一条用户消息一轮回复，自然停即停；
  max_tokens 截断续跑不受影响（内核自行注入 Continue），长文档产出在会话内仍连贯；
- **预算作用域**：BudgetGuard **会话级一份**（跨连接与回合持续累计），上限自 `RA_MAX_*`
  继承（D4 不放宽）；断连重连不重置，run.json 保留最近一次落盘的快照供参考；
- **回合与连接解耦（R16）**：回合的全部可迁移状态装在 `_TurnHandle`（task、cancel_event、
  审批/steer 队列、帧环形缓冲与 seq、partial_text、status、observers），socket 只是其一
  观察者——连接退场不触碰回合，收尾写回与注册项摘除由 `_turn_main` 的 finally 统一负责。

## 11. 执行环境契约（R12）

> 实现权威：`core.execution_contract_addendum()`（提示层）、`tools/bash.py`（拦截层）、
> `tools/frozen_exec.py`（运行时层）、`desktop.workspace_arg_error()`（入口层）。
> 背景：打包版目标机没有独立 Python，v3.3.3 验证时模型自创
> `subprocess([sys.executable, script.py])` 把应用 exe 再启动一遍，弹「目录不存在」对话框。
> 契约把「正确行为」从模型临场发挥升级为产品保证——四层防御。

### 11.1 提示层（addendum 注入）

`execution_contract_addendum()` 按 `sys.frozen` 返回冻结契约或一行开发态说明。冻结文本要点：

1. 禁止经 bash/subprocess 调用任何 python/pip/python3/py——`sys.executable` 是本应用自身，
   当解释器启动会重启整个桌面应用；
2. 一切 Python 经 **run_python** 工具（进程内沙箱，内置 numpy/pandas/matplotlib 等）；
3. 运行 .py 脚本文件用 run_python 内可直接调用的助手 **`run_script(路径, argv=None)`**
   （正确设置 sys.argv / `__name__="__main__"` / `__file__`，可导入兄弟模块）；
4. 全局常量 **`WS`** = 工作区根绝对路径；产物写入系统提示给出的产物目录，跨目录读写用绝对路径。

注入三 choke point（一处函数、三处消费）：`config.build_system_instructions`、
pipeline `_run_stage_agent`（覆盖全部阶段与 resume 重放）、chat `_chat_system_instructions`。
旧 orchestrator 助手提示同加。

### 11.2 双目录口径（会话模式）

会话 ToolRegistry：`work_dir=工作区根`（sandbox 围栏不变）+ `write_anchor=exec_cwd=outputs/<sid>`：

- **write_file 相对路径一律解析到 anchor**（确定性归巢，仍过 safe_resolve 围栏）；anchor 内/
  sandbox 内绝对路径原样；越界报错不变。成功回执回显**最终绝对路径**。
- **edit_file 保持根解析**：「改共享文件」语义响亮且正确；write_file 一律归巢保证会话永不静默覆写共享文件。
- **bash/run_python 默认 cwd = anchor**；显式 path 参数仍优先。
- 会话系统提示明确：产物进专属目录、读共享数据用绝对路径或 `WS`、不要写进 `writing_outputs/`（任务领地）。
- 任务流水线只加 `write_anchor=<paper_dir>`（exec_cwd 不动=CWD 根）——阶段提示词全绝对路径，
  杂散相对写自然落入论文目录。

### 11.3 运行时层

- **frozen_exec 子进程 globals** = `{__name__, __file__, WS, run_script}`（pickle 传递
  `workspace_root`；registry 的 run_python 分支恒传 `self.work_dir`）。`cwd` 不存在仍硬失败
  （B4 已保证连接时 mkdir）。
- **bash python 守卫**（仅 `sys.frozen`）：按操作符（`&& || | & ;`）切段，逐段跳过前导
  `KEY=VALUE` 后取 basename（去 `.exe`），命中 `python/python3/py/pip/pip3` 或 `python*`
  前缀（不误伤 ipython）→ **不 spawn**，返回中文替代路径指引。残余旁路（`where python`
  等无害读命令）有意放行。
- **入口防线**：desktop 位置参数为文件 → 定向文案（解释 sys.executable 成因 + 指向
  run_python），非目录 → 目录不存在文案；均 exit 2。桌面壳 main() 自动置
  `RA_ALLOW_SHELL_OPEN=1`（§8）。

### 11.4 已知缺口

- `verify_citations` 处理器以相对路径写 output_file 时不经过 write_anchor（独立处理器路径，
  未走 registry 注入）——调用方需传绝对路径。
- bash 守卫只在冻结态生效；开发态系统 Python 存在，无需拦截。

## 12. 科研操作系统增量契约（schema v10）

### 12.1 审批、Agent roster 与搜索

- `GET /api/approvals?status=pending` 返回 project-scoped 持久化审批收件箱；
  `POST /api/approvals/{id}/resolve` 必须携带 `approved`，服务端仍会校验当前任务的
  `request_id`，迟到或伪造回执不会消费下一次审批。
- `GET /api/tasks/{task_id}/agents` 返回工作流节点对应的 Agent/role、状态、耗时、错误和
  最近 Agent Items，供任务详情面板轮询；任务、线程和 Agent Items 始终以 project_id 隔离。
- `agent_runs` 持久化每个 task/agent 节点的 role、model、status、budget、inputs、outputs、
  起止时间和错误；`GET /api/agent-runs?task_id=...` 提供 project-scoped 查询，研究包导入导出
  会保留这些记录。
- `GET /api/project/search?q=...` 统一检索线程、任务、资料、研究对象、主张、决策和产物；
  前端通过 Ctrl/Cmd+K 打开命令式搜索入口，结果只导航到真实对象页面。
- `GET /api/project/activity?after=...` 返回任务事件、Agent Item、通知、质量项和产物审阅
  合并后的项目活动流；新客户端可使用响应中的 `next_cursor`（`时间戳|ID`）继续读取，
  同一时间戳的事件不会漏项，`after` 保留用于旧客户端兼容；`Project Home` 展示最近窗口。

### 12.5 外部核验连接复用

Citation Verify 按 asyncio 事件循环复用 `httpx.AsyncClient` connection pool，避免多 Agent
或多批次引用核验反复建立 TCP/TLS 连接；Web 宿主 lifespan 退出时显式关闭池。跨事件循环
调用仍会自动创建独立池，避免桌面测试和后台宿主互相污染。

### 12.2 质量与来源变更

`artifact_reviews.metadata` 中 `quality_gate_status=failed` 或任一 `quality_gates[].passed=false`
时，`accepted` 状态会被拒绝；审阅更新会合并既有 metadata，避免评论回写覆盖 hash/门禁信息。
删除资料后，所有引用其 source_id 的主张都会产生 `source_integrity` warning，必须重新审阅
证据链后才能恢复可信状态。
质量报告同时计算 `contradicted`、`conflicted`、`stale_evidence`、孤儿证据和失败运行；存在
冲突或过期证据时 `ready_for_synthesis=false`。来源删除会为受影响主张写入
`source_integrity` warning。

### 12.3 研究包冲突策略

`POST /api/project/import?conflict=skip|overwrite|rename` 默认 skip，响应包含 `conflicts`、
`imported` 和 `conflict_strategy`。`rename` 为冲突文件生成 `.import-N` 后缀；manifest 合并
仍使用 INSERT OR IGNORE，且不会导入 `.env`、`.ra`、VCS、缓存或队列 worker 内部字段。

### 12.4 输入与运行环境可复现性

分析运行 manifest 保存输入文件 SHA-256、列名/类型/shape schema、Python/platform/executable
环境快照和项目依赖锁（`pyproject.toml` hash、声明依赖版本、确定性 lock hash）。
`GET /api/analysis/environment` 可查看当前项目锁。复现时对 hash、schema、依赖锁和 runtime
差异生成 outputs/quality_items，差异必须在产物审阅或研究报告中明确处理。

### 12.5 性能验收

`scripts/perf_research_os.py` 在隔离 SQLite 工作区中生成 1,000 条事件、500 个证据片段和
100 个任务，并测量事件读取、证据矩阵、任务列表和项目摘要。脚本输出
`[PERF-RESEARCH-OS] PASS` 后才算完成计划中的合成性能验收；数据库连接在每次事务后显式
提交并关闭，避免 Windows 文件句柄泄漏拖慢后台任务和阻止项目删除。
