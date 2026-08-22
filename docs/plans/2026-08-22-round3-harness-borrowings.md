# Round-3 改造计划：借鉴 Codex / DeepSeek Harness

> 来源：2026-08-22 对 openai/codex 与 deepseek-ai/deepseek-harness 的实时对比分析。
> 原则：只借鉴两家共同验证、且与我们单人维护规模匹配的机制；不做全插件化。

## 借鉴项与设计决策

### P0-A 审批三态（allow / deny / ask）—— 来自两家共同的 ctx.approval 模式
- `HookVerdict` 增加 `ask: bool`；PRE_TOOL_USE 返回 ask 时路由给 approver 回调；
- **无 approver 或超时（默认 120s）一律 deny**（照抄 dsh 规则："absent or unanswerable: deny"）；
- 新类型：`ToolApprovalRequest{tool_name,arguments,turn}` / `ApprovalDecision{approved,note}`；
- CLI：队列复用式问询（审批请求打印到终端，回复从现有 steer 队列读取），`RA_APPROVAL_MODE=off|interactive`，默认 off=自动拒绝并提示（零行为变更）；
- Web：服务端推送 `{type:"approval_request"}`，前端确认后回 `{action:"approval"}`；断线/超时=deny。

### P0-B 会话日志升级为"模型可见即已记录" —— 来自 dsh 核心不变量
- `RunConfig.session_log` 端口（任何实现 `.log(kind,data)` 的对象）；agent 内所有对
  `messages` 的增删改同步镜像到日志：msg_add / tool_call / tool_result / compaction /
  llm_meta / steer / run_end；
- 运行时不变量检查：每次 LLM 请求前校验消息序列已被日志覆盖（含压缩区间登记），
  缺口记 `invariant_warning` 事件（软警告不中断运行——与 dsh 硬断言的差异记录在案）；
- 单条日志上限 20k 字符（超大内容已由外置化兜底）。

### P1-C 重复工具调用守卫 —— 来自 dsh guard/repeat-tool-reminder
- `kernel/guards.py: RepeatToolCallGuard(limit)`：同名同参连续调用达限（默认 3，
  `RA_REPEAT_TOOL_LIMIT` 可调，0=关）即 deny 并提示模型改变方法；
- 默认启用，挂载在现有 HookBus 上，与权限策略共存。

### P1-D post-execute 结果改写钩子 —— 来自 dsh tools/post-execute 瀑布
- 新事件 `TOOL_RESULT_REWRITE`：处理器返回字符串则替换工具结果（首个非 None 生效），
  在外置化之前执行（改写产物同样享受外置化）。

### P2-E 执行世界 provider seam —— 来自 dsh fs/process seam（方向性落地）
- `tools/exec_provider.py`：`ExecProvider` 协议 + `LocalExecProvider`（现行为原样封装）；
  ToolRegistry 通过它分发 bash/run_python；远程/容器 provider 留作扩展点。

### P2-F 协议文档化 —— 来自 codex protocol_v1.md 的工程实践
- `docs/protocol.md`：run.json schema、events.jsonl 事件目录、HookVerdict/审批契约。

## 明确不做
Cordis 式全插件化（抽象税>收益）、e2b 远程沙箱实体实现（仅留接口）、Codex SDK 替换内核（见战略分析）。

## 执行分工
- 主会话（我）：A/B/C/D 全部内核链路 + cli/api/pipeline 贯穿 + 测试
- 后台 Agent-1：E 执行 provider seam（独立文件域 tools/*）
- 后台 Agent-2：Web 审批前端卡片（static/*，契约由主会话先行落地的 ws 代码决定）
- 后台 Agent-3：F 协议文档（代码落地后撰写）

## 验收
pytest 全绿（新增 ≥15 用例）、ruff 0 错误、默认行为零破坏
（RA_APPROVAL_MODE=off 时老用户无感）。
