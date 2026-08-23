# Research Assistant Harness 协议规格

> 版本：schema_version = **1** · 更新日期：2026-08-22
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
  "query": "...", "model": "...", "mode": "pipeline | single",
  "stage": "<最后活动的阶段名>",
  "status": "running | complete | failed | cancelled",
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
（修订轮记为 `revision_<n>` 子代理）。单代理模式只产生 `mode:"single"` 与事件日志，无阶段记录。

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
    async def run_python(self, code: str, timeout: int, cwd: str) -> str: ...
```

`ToolRegistry(exec_provider=None)` 默认装配 `LocalExecProvider`（委托现有本地实现）。替换 provider 即把 bash/run_python 整体迁移到其他执行世界（容器/远程沙箱），工具定义与提示词零改动。扩展点仅此一处，暂无远程实现。

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

## 9. 版本化承诺

1. 任何破坏 `run.json` / `events.jsonl` / HookVerdict 语义的改动必须递增 `SCHEMA_VERSION`；
2. 读取端必须容忍未知字段与未知 kind（现实现已满足：`SessionState(**known_only)`、逐行 try-parse）;
3. 新增枚举值/事件 kind 不算破坏性变更（消费方按白名单处理的应忽略未知值）。

## 10. 会话协议 (/ws/chat)（R2）

> 实现权威：`web/chat.py`；前端消费方：`static/js/protocol_chat.js`（reduceChat 纯函数归约）、`static/js/views/chat.js`。
> 挂载：同一 router include 两次 —— REST 带 `prefix="/api"`，WS 无前缀落在 `/ws/chat`。

### 10.1 会话目录与持久化（D2）

每会话一个目录 `<workdir>/.ra/sessions/<YYYYMMDD_HHMMSS_slug>/`：

| 文件 | 角色 |
|---|---|
| `run.json` | SessionStore 状态机；`mode:"chat"`、`status: running/complete/cancelled/failed`、预算快照 |
| `events.jsonl` | kernel 逐条审计镜像（§3 目录），不用于重建 |
| `history.json` | **对话唯一权威**（D2）：`{"schema_version": 1, "messages": [{"role": "user"\|"assistant", "content": str}, ...]}` 归约文本往来；每轮结束整份写回，重启即恢复。工具调用明细不入 history（前端恢复只渲染文本往来） |

slug 由可选标题派生（保留 CJK）；同秒重名追加 `_n` 序号。

### 10.2 REST（挂载于 `/api` 前缀下）

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/api/chat/sessions` | body 可选 `{"title": str}` | `{"id", "created_at"(epoch 秒)}` |
| GET | `/api/chat/sessions` | — | `[{id, title?null, last_message(≤80字), turns(用户消息数), created_at, updated_at}]` 按 updated_at 倒序。列表前先清退**零轮次且 updated_at 距今 > 1h** 的目录（用户消息回合开始前先落盘，零轮次 = 从未收到用户帧，删除不丢内容；§6.4 空会话治理） |
| GET | `/api/chat/sessions/{id}` | — | `{id, messages:[{role,content}...]}`（history.json 全量）；未知 404、非法 ID 403 |
| DELETE | `/api/chat/sessions/{id}` | — | `{ok:true}` 删除整个目录 |

### 10.3 WS 帧 schema

连接：`GET ws://host/ws/chat?session=<id>`；`session` 缺省则新建会话；给出的 id 已被删除时按同名幂等重建（不卡 UI）；含路径分隔符/盘符的 id 发 `error` 帧并关闭。

**server → client**

| type | 字段 | 说明 |
|---|---|---|
| `connected` | `session_id` | 握手完成，可发消息 |
| `text` | `delta` | 流式正文增量；接续最后一个 text 气泡（前端合并） |
| `tool_card` | `id`, `tool`, `arguments`, `status: running\|done\|error`, `result_preview`(≤400字), `files:[{path}]` | 同 `id` 多次推送按卡合并；`files` 从 write_file/edit_file 的 `file_path` 与 bash/run_python 结果文本的扩展名启发式提取（去重保序，≤8 条） |
| `usage` | `budget`: BudgetGuard.snapshot() | 运行期约每 1s 一帧，结束至少一帧（复用 B5 usage_ticks） |
| `approval_request` | `id`, `tool`, `summary` | PRE_TOOL_USE ask 升级时推送；`id` 为本次问询唯一标识 |
| `result` | `stop_reason`, `turns` | 一轮结束。stop_reason 枚举同 AgentResult（completed/cancelled/budget_exceeded/max_turns/max_continuations） |
| `error` | `message` | 校验失败/运行异常/配置错误（如缺 API key） |

**client → server**

| action | 字段 | 说明 |
|---|---|---|
| `user` | `text`(≤8000) | 触发一轮；空/超长发 `error` 且不启动循环 |
| `approval` | `id`, `approved` | 应答当前问询；`id` 与待答请求不符（迟到/伪造）直接忽略，防止残留答案自动放行下一次问询 |
| `steer` | `message`(≤2000) | 运行中注入 steer_queue（内核下一轮首并入 user 消息）；空闲期收到则入队、下一轮开始时生效 |
| `stop` | — | 置位 cancel_event，协作停止本轮（结果帧 stop_reason=cancelled） |

未知 action/type 均容忍（error 帧 / 忽略），符合 §9 承诺。

### 10.4 生命周期

```
浏览器                                ws_chat 服务端
  │── GET /ws/chat?session=<id> ──▶ accept；定位/新建会话目录
  │                                  同会话并发：后连者 close(4001) 踢前者
  │◀── {"connected", session_id} ──┤ 组装：BudgetGuard(RA_MAX_* 继承)、
  │                                  QueueApprover、ToolRegistry(cwd 围栏)
  │── {"action":"user","text"} ───▶ ┌ 一轮（_run_turn）
  │◀── text delta × N（流式）       │   history.json 载入 → 追加 user → 落盘
  │◀── tool_card(running)          │   run_agent(on_text/on_tool_start/on_tool_use,
  │◀── tool_card(done,files[])     │            steer_queue, cancel_event, approver)
  │◀── usage × N（≈1s 一帧）        │   结束：assistant 回复写回 history.json
  │◀── {"result",stop_reason,turns}┘   SessionStore.finish(status, 预算快照)
  │── steer/approval/stop ────────▶ 泵任务并发接收分发（轮次期间）
  │── 断开 ──────────────────────▶ cancel_event 置位 + 问询队列投 None（等效拒绝）
```

### 10.5 内核适配说明

- **流式**：run_agent 传入 `on_text` 即走流式路径（on_chunk 逐段回调），故 `text` 帧为真实增量；
- **多轮历史**：run_agent 每轮从全新 messages 起步，无初始历史参数——由模块内
  `_HistoryClient` 包装层补足：检测到本轮首个请求形态（单条 user 消息）时把
  history.json 的归约历史前置拼接（重试同样展开；用量按含历史的真实请求计量）；
- **auto_continue=False**（有意偏离 generate 流程）：一条用户消息一轮回复，自然停即停；
  max_tokens 截断续跑不受影响（内核自行注入 Continue），长文档产出在会话内仍连贯；
- **预算作用域**：BudgetGuard 每连接一份（跨轮累计），上限自 `RA_MAX_*` 继承（D4 不放宽）；
  断连重连后重新起算，run.json 保留最近一次落盘的快照供参考。

