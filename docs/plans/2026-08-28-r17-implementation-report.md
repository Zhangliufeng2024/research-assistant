# R17 重构实施报告（5 阶段全部落地）

日期：2026-08-28
前置：`2026-08-28-panel-and-storage-refactor-assessment.md`（评估）、`2026-08-28-refactor-plan-detailed.md`（计划）
验证基线：pytest **1010 passed**（基线 966 + 新增 44，4 个已知环境性失败不变）、vitest **266 passed**（基线 252 + 新增 14）、tsc clean、ruff clean。

---

## 阶段 0：基础设施 ✅

- `config.feature_flag(name, default)`：统一 `RA_FF_*` 读取（真值集 1/true/yes/on）。
- `scripts/migrate_workspace.py`：dry-run 默认、`--apply` 实执行、迁移前检测运行中任务（有则拒绝）、备份到 `.ra/migration_backup/<ts>/`；首个 step=`outputs`（writing_outputs → .ra/outputs）。

## 阶段 1（P0）：对话↔任务互链 + 状态持久 ✅

后端
- platform_store SCHEMA 10→**11**：新表 `session_meta(session_id, pinned, archived, updated_at)`；`tasks.source_session_id` 列（幂等 ALTER，旧库打开自动升级，有测试覆盖）。
- 链路打通：`POST /chat/sessions/{id}/promote`（打包最近 ≤20 条/≤6000 字符上下文入队）→ payload 携 `source_session_id` → dispatcher → `hub.start` → `create_task` 落库。
- `POST /chat/sessions/{id}/flags`（pinned/archived 服务端持久化）；`list_sessions` 合并 pinned/archived/derived_run_count 并按置顶优先排序。
- `generate_session_dir_name`：6 位随机后缀（同秒 200 并发零撞名）+ slug 保留 CJK（中文会话目录可读）。

前端
- SessionList：归档/置顶改走服务端 API；localStorage 旧归档**一次性自动迁移**（`ra.flags-migrated.v1` 标记）；时间分组渲染（置顶/今天/本周/更早，`sessionGroups.ts` 纯函数）；派生任务徽标（任务 N）。
- ChatView 工具条新增「转为任务」；`chatStore.promoteSession`。
- TasksView：`SourceSessionLink`（任务卡→来源对话回链，后台/可恢复/检索结果三处接入）。

## 阶段 2（P1）：导航与存储生命周期 ✅

- `/chat/:sessionId` 深链路由化（ChatView 双向同步 URL，replace 不污染历史栈）；通知中心 object_id → 「查看来源」跳转。
- `GET /api/runs/search`（标题子串+状态+分页，返回 total）+ TasksView「任务检索」面板（防抖 300ms、状态筛选、翻页）；`slice(0,20)` 保留为最近视图并注明检索入口。
- Scheduler 触发器：`PATCH/DELETE /api/scheduler/triggers/{id}` + 规则卡片（人性化间隔描述、启停开关、两段式删除、下次/上次运行）。
- **Janitor**（`runtime/janitor.py`，挂 DurableScheduler 主循环，`RA_JANITOR_INTERVAL_SECONDS=3600`）：
  - 温层 30d 未动 → 标记 archived（不动文件）；冷层 90d 且已归档 → events.jsonl gzip + 产物 drafts/ 删除（artifacts/ 保留）；
  - .ra/changes 500MB LRU 淘汰；events.jsonl 10MB×3 代轮转；tmp/ 7d 清扫；
  - **冷层先于温层执行**（先观察后销毁：本轮新归档的下一轮才可能被压缩）；
  - 一切动作先写审计 `.ra/janitor_audit.jsonl`；热层零触碰有红线测试。
- outputs 迁移期双轨：`.ra/outputs/` 存在即优先（`_outputs_root`），新会话写新位置，旧位置只读兜底。
- 仓库根卫生：15 个 `.pytest_tmp*` 清除；`plan260824.md` → `docs/plans/2026-08-24-plan.md`（PROJECT_STATUS.md 引用同步）；.gitignore 的 `*.spec` 自相矛盾修正（`!ResearchAssistant.spec`）。

## 阶段 3（P2）：任务中心 + 思考链 A 层 ✅

- 状态枚举收敛：`RUN_STATUS_LABEL` 扩为 queued/running/stopping/complete/failed/cancelled/interrupted 单一来源；`legacy/早期文档` 文案退役（未知状态按 interrupted 风格兜底，不再占用状态位）。
- `StatusStrip`（任务面板头部状态带：排队→运行→待批准→终态，待批准脉冲、终态按结果着色）；`KanbanBoard`（进行中/已完成/失败中断/已取消四列，列表/看板可切换，默认列表）。
- **思考链显示分级（A 层）**：
  - 三档 verbosity（简洁/标准/调试），`prefsStore` 双写 localStorage + `/api/settings/ui.verbosity`（platform meta 表，跨端）；ChatView 工具条档位切换钮。
  - ToolCard 完整参数 JSON 降 L2（仅调试档显示）；planner 直播打 `channel="plan"` 折叠进 L1（不再污染正文气泡）；
  - error 帧附可选 `traceback`（截尾 4000 字符），调试档横幅可展开堆栈；
  - `ThinkingBlock` 组件：折叠一行（图标+字数+首行摘要），standard 档运行中自动展开、完成折回，debug 档默认展开。
- 统一检索 `GET /api/search`（sessions+tasks，Ctrl+K/历史页共用）。

## 阶段 4（P3）：真实 reasoning 通道 ✅

- LLM 层：`AnthropicClient` 解析 `thinking_delta`、`OpenAICompatClient` 读 `reasoning_content`/`reason_content`，统一 `on_thought` 回调（此前两者均被静默丢弃）；`base.LLMClient.chat` 契约明确「思考绝不混入 content」。
- 管道：`run_agent(on_thought=)` → chat.py `_on_thought` → text 帧 `channel="thought"`（不加新帧型，旧客户端忽略即回落）。
- 红线有测试：思考不入 partial_text、不入 history.json 落盘（`test_r17_thought.py` 端到端验证）。
- 前端 `ThinkingBlock` 渲染 thought 气泡；`RA_PERSIST_THOUGHTS` 预留落盘开关（默认不落盘）。

##  deferred（明确未做，建议下一迭代）

| 项 | 原因 |
|---|---|
| navModel 侧栏 5 分区重组（进行中/看板/计划/历史/通知独立 tab） | 能力已就地位（检索/看板/规则卡片进 TasksView，触发器管理进 SchedulerView）；纯导航重组影响面大，建议单独灰度 |
| manifest.json + artifacts 表（产物级检索） | `/api/search` 已覆盖会话+任务；产物索引待资料库页改版时一并做 |
| 分屏对照（CodePilot 式 split screen） | 计划内即标注 P3 独立迭代 |
| 每消息尾「查看过程 N 项」 | L1 折叠块已内联于消息流，信息等价；聚合入口待真实使用反馈 |

## 协议与文档

- `docs/protocol.md`：text 帧 channel 字段、error 帧 traceback、6 个新 REST 端点、RA_FF_*/RA_JANITOR_* 环境变量入 §8 总表。

## 新增测试（58 个）

- 后端 44：`test_r17_platform.py`（28：flag/命名/schema v11/标志位/互链/检索/触发器/flags REST/promote）、`test_r17_janitor.py`（11：分层/红线/审计）、`test_r17_thought.py`（5：两 provider + WS 端到端）。
- 前端 14：`sessionGroups.test.ts`（8）、`r17Channels.test.ts`（6）。
