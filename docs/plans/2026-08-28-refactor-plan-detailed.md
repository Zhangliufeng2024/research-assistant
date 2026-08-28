# 重构详细计划：面板 IA / 对话-任务关联 / 文件管理 / 思考链显示策略

日期：2026-08-28
前置文档：`docs/plans/2026-08-28-panel-and-storage-refactor-assessment.md`（现状评估）
本文档：可执行的实施计划，含任务分解、验收标准、依赖关系、回滚方式。

---

## 〇、总体路线

```
阶段0 准备     ──►  阶段1 (P0)     ──►  阶段2 (P1)      ──►  阶段3 (P2)      ──►  阶段4 (P3)
feature flag        对话↔任务互链      会话路由化            看板/状态带          分屏对照
迁移脚本骨架        归档入SQLite       历史搜索分页          思考链显示分级 ──┐    真实 reasoning 接入
基线测试            session_id后缀     outputs并入.ra       manifest+search   │    （依赖阶段3通道）
                                       Janitor清理          Scheduler卡片化   │
                                                              └──────────────┘
                                                         （显示分级先行，真思考链后接）
```

**全局原则**
1. 所有破坏性变更（目录迁移、归档行为变化）必须带迁移脚本 + 回滚路径，先灰度（`RA_FF_*` feature flag 环境变量）后默认。
2. 每阶段结束跑全量基线：`PYTHONPATH= python -m pytest -p no:cacheprovider --basetemp=.pytest_tmpX` + `vitest run` + `tsc --noEmit` + `ruff check`。
3. 协议变更（新帧/新字段）遵循 `docs/protocol.md` 既有惯例：新增字段可选、旧客户端忽略未知帧，禁止改语义。
4. 每阶段一个独立 commit/PR，单独可回退。

---

## 一、思考链显示策略（专项设计，贯穿阶段3-4）

### 1.1 现状定性

**项目当前没有思考链。** `llm/anthropic.py:282-292` 丢弃 thinking block，`llm/openai_compat.py:224-247` 不读 `reasoning_content`；前端"思考流"实为正文 text 帧。因此本策略分两层：
- **A 层（阶段3，立即可做）**：对现有过程性内容（工具卡、planner 直播、预算、错误）建立显示分级；
- **B 层（阶段4，可选启用）**：接入真实 reasoning 通道，复用 A 层的分级容器。

### 1.2 显示分级矩阵

| 级别 | 内容 | 默认行为 | 理由 |
|---|---|---|---|
| **L0 始终显示** | 用户消息、助手正文、审批卡（ApprovalCard）、计划待决卡（PlanCard）、错误摘要横幅 | 展开，不可隐藏 | 需要用户行动或构成对话主线的内容；审批/计划是唯一的交互入口，藏了会卡死流程 |
| **L1 默认折叠·一眼摘要** | 工具调用卡（ToolCard）、真实思考块（B层接入后）、planner 过程直播、压缩/steer 提示 | 折叠为一行摘要（工具名+关键参数≤80字+状态徽标）；点击展开 | 过程证据，审计时需要，阅读时干扰。沿用 ToolCardView 现有折叠模式，扩展到所有过程内容 |
| **L2 仅"详细模式"** | 工具参数完整 JSON、工具结果全文、usage/预算逐帧快照、错误堆栈、replay/心跳帧、token 计数 | 全局开关开启才渲染 | 调试价值高、信息密度低。参考 CodePilot 的 `/doctor` 诊断与 WorkBuddy 的开发者选项 |
| **L3 永不进 UI** | 系统提示词、内部 steer 指令原文、被截断的中间 partial 消息、密钥/环境变量、`_ra_exec_*` 草稿内容 | 不下发或前端丢弃 | 安全与信噪比底线；其中密钥类后端就不该进帧 |

**关键修正项（现状不符的）**：
- ToolCard 展开后参数是 `JSON.stringify` 全文（ToolCardView.tsx:152）→ 降为 L2，L1 摘要保留 `argsSummary`；
- PlanCard 计划全文直铺 → 保持 L0（需要决策），但超过 40 行时折叠为要点 + 「展开全文」；
- planner 直播（/plan 门的 text 帧流）→ 从正文气泡剥离，归入 L1 折叠区，避免计划过程污染对话正文；
- 错误只有 message 无堆栈 → L0 显示人性化摘要 + L2 显示堆栈（后端 error 帧增加可选 `traceback` 字段）。

### 1.3 显示级别设置（新增）

三档全局 verbosity，存 platform.sqlite3（替代纯 localStorage，与归档迁移同批做）：

| 档位 | L0 | L1 | L2 | 适用 |
|---|---|---|---|---|
| 简洁（默认） | 展开 | 折叠一行 | 隐藏 | 日常写作/研究 |
| 标准 | 展开 | 默认折叠、运行中自动展开当前工具卡 | 隐藏 | 想观察执行过程 |
| 调试 | 展开 | 展开 | 展开 | 排错、开发 |

另加每条助手消息尾部的「查看过程 N 项」入口（N = 该回合折叠的 L1 项数），实现"正文干净、过程可溯"。

### 1.4 B 层：真实思考链接入预案（阶段4）

- LLM 层：`anthropic.py` 解析 `thinking_delta`、`openai_compat.py` 读 `reasoning_content`，统一为内部事件 `ThoughtDelta`；
- 协议：text 帧加可选 `channel: "content" | "thought"`（不加新帧型，旧客户端忽略 channel 字段即回落现状）；
- 落盘：`events.jsonl` 已有 kind 惯例，thought 以 `msg_add` 的 `channel=thought` 落盘，**默认不落盘**（`RA_PERSIST_THOUGHTS=1` 开启），避免历史体积膨胀与隐私外溢；
- 前端：新 `ThinkingBlock` 组件复用 ToolCard 折叠壳，标题显示"思考 · Xs"，流式时标题后转圈，完成定格；
- 硬约束：思考内容**绝不进 L0**；长思考（>500 字）折叠后摘要只显示首行。

---

## 二、阶段任务分解

### 阶段 0：准备（0.5 天，无用户可见变化）

| # | 任务 | 改动点 | 验收 |
|---|---|---|---|
| 0.1 | feature flag 机制 | `config.py` 增加 `RA_FF_*` 读取（默认全关） | 单测覆盖 flag 开关两态 |
| 0.2 | 迁移脚本骨架 | `scripts/migrate_workspace.py`：dry-run 默认、备份到 `.ra/migration_backup/`、逐工作区执行 | 对本仓库 dry-run 输出零改动 |
| 0.3 | 基线快照 | 记录当前 pytest/vitest/tsc 基线入 `docs/plans/` | 基线文件入库 |

### 阶段 1（P0）：上下文互链 + 状态持久（约 3 天）

| # | 任务 | 改动点 | 验收标准 | 依赖 |
|---|---|---|---|---|
| 1.1 | `RunSummary.source_session_id` + `SessionSummary.derived_run_count/pinned/archived` | platform_store.py（SCHEMA 10→11，加列迁移）、types.ts、protocolTask/Chat | 老库打开自动 ALTER；新任务可携带来源会话 id | 0.1 |
| 1.2 | 对话→任务：「转为任务」动作 | MessageBubbles 工具条 + chatStore + `web/chat.py` 新 endpoint（打包上下文 → 排队 Run） | 从对话建任务后，任务详情显示来源卡，点击回跳对话 | 1.1 |
| 1.3 | 任务→对话：详情头部来源卡片 | TasksView 详情头组件 | 无来源的任务不渲染卡片（兼容存量） | 1.1 |
| 1.4 | 会话徽标：派生任务计数内联展开 | SessionList 列表项 | 徽标计数与任务中心数据一致 | 1.1 |
| 1.5 | 归档迁入 SQLite + localStorage 一次性迁移 | sessionArchive.ts 废弃；chat.py 归档 API；启动时迁移 `ra.archived-sessions.v1` | 归档换浏览器可见；旧 key 迁移后清除 | 1.1 |
| 1.6 | 会话时间分组 + pinned | SessionList：置顶/今天/本周/更早/已归档五段 | 纯前端归约，单测覆盖分组边界（跨午夜） | 1.5 |
| 1.7 | session_id 加 rand4 后缀 + slug 保 CJK | `config.py:20` generate_session_dir_name | 并发 100 创建零撞名；中文会话目录名可读 | — |

**回滚**：1.1-1.6 全为增量字段/新 UI，flag 关闭即回旧态；1.7 仅影响新会话。
**风险**：1.5 的迁移要在首次写入前完成，需启动锁防双写。

### 阶段 2（P1）：导航与存储生命周期（约 4 天）

| # | 任务 | 改动点 | 验收标准 | 依赖 |
|---|---|---|---|---|
| 2.1 | `/chat/:sessionId` 路由化 | App.tsx、ChatView、Sidebar；`/chat` 保留为新会话 | 深链直达、浏览器前进后退可用；旧 `/threads/:id` 301 兼容 | 1.5 |
| 2.2 | 通知中心 object_id 跳转 | NotificationsView → 按 object_type 路由到会话/任务 | 点击通知落点正确 | 2.1 |
| 2.3 | 历史运行：搜索/筛选/分页 | platform_store `search_runs()`（LIKE + 状态/时间过滤 + LIMIT/OFFSET）、TasksView 历史区替换 `slice(0,20)` | 1000 条记录下首屏 <200ms；翻页不丢筛选 | 1.1 |
| 2.4 | Scheduler 启停/删除 | scheduler.py API + SchedulerView 开关与删除按钮 | trigger `enabled` 可切换、立即生效 | — |
| 2.5 | outputs 并入 `.ra/outputs/<id>/` | 迁移脚本（0.2）+ chat.py:79/281/516 + workspace.py；删除会话改单 rmtree | 存量 writing_outputs 全量搬迁且 `outputs_dir` 指针更新；旧目录校验为空后归档为 `.ra/migration_backup/legacy_outputs/` | 0.2 |
| 2.6 | Janitor 统一清理 | scheduler.py 挂周期任务：温层归档标记 / 冷层 gzip+清 drafts / changes LRU(50份/会话,500MB) / events.jsonl 轮转(10MB×3) / tmp 7天清扫；**全部先写审计日志** `.ra/janitor_audit.jsonl` | 策略全部可配（`RA_JANITOR_*`），默认只动 archived；审计日志逐条可查 | 2.5 |
| 2.7 | 仓库根卫生 | 16 个 `.pytest_tmp*` 清除入 `tmp/pytest/`；`plan260824.md` 迁 `docs/plans/`；修 .gitignore 的 `*.spec` 自相矛盾 | git status 干净；打包脚本不受影响 | — |

**回滚**：2.5 是唯一的结构性变更——迁移脚本保留原目录树备份，flag 切回即读旧路径。
**风险**：2.5 与正在运行的会话冲突——迁移前须停所有 Run（脚本内置运行中检测并拒绝执行）。

### 阶段 3（P2）：任务中心成形 + 思考链 A 层（约 5 天）

| # | 任务 | 改动点 | 验收标准 | 依赖 |
|---|---|---|---|---|
| 3.1 | 任务中心 5 分区 IA | navModel.ts：进行中/看板/计划/历史/通知；SchedulerView 迁入「计划」 | 旧 `/scheduler` 路由重定向；导航最深≤2层 | 2.3, 2.4 |
| 3.2 | 状态枚举收敛 | `TaskPhase` 与 `RUN_STATUS_LABEL` 并为一个枚举，消灭 `legacy` 兜底文案 | 全 UI 状态文案唯一来源 | — |
| 3.3 | 状态带 StatusStrip | 任务详情头：`queued→running→(approval⇄running)→done/failed/cancelled` 横向状态机，失败节点点击跳 ActivityFeed 错误行 | 各终态/审批回环路径渲染正确 | 3.2 |
| 3.4 | 看板视图 KanbanBoard | 新组件；拖拽 awaiting_approval 卡片 = 快捷批准 | 默认仍是列表视图，看板为切换项 | 3.2 |
| 3.5 | 触发器规则卡片化 | 自然语言时间描述 + 启停 + 近5次运行红绿灯 + 展开派生历史 | cron 与间隔双模式可用 | 2.4 |
| 3.6 | **思考链 A 层分级**（见第一节矩阵） | verbosity 三档入 platform.sqlite3；ToolCard 参数全文降 L2；planner 直播剥离正文入折叠区；error 帧加可选 traceback；消息尾「查看过程 N 项」 | 简洁档下长回合正文无过程噪音；调试档可见堆栈与全参数 | 1.1（存储） |
| 3.7 | manifest.json + artifacts 表 + 统一 `search()` | 每会话产物清单落盘；platform_store `search(query, scope)`；WorkspaceSearch 与历史页共用 | Ctrl+K 可搜到产物文件 | 2.5 |

**回滚**：3.1-3.5 为新视图，flag 控制；3.6 的 verbosity 默认"简洁"，旧行为≈"标准+L1全展开"，可在设置一键还原。

### 阶段 4（P3）：增强（独立迭代，不在本次承诺范围）

- 4.1 分屏对照（ChatView 双栏，参考 CodePilot split screen）
- 4.2 真实 reasoning 通道（第一节 B 层：LLM 层解析 → text 帧 channel 字段 → ThinkingBlock）
- 4.3 思考摘要（可选：长思考生成一句话摘要进 L1 标题）

---

## 三、工作量与里程碑

| 里程碑 | 内容 | 预估 | 交付物 |
|---|---|---|---|
| M1 | 阶段 0+1 | 3.5 天 | 对话↔任务互链可用、归档持久化、撞名根治 |
| M2 | 阶段 2 | 4 天 | 深链导航、历史可搜、存储有生命周期 |
| M3 | 阶段 3 | 5 天 | 任务中心完整 IA、思考链分级上线 |
| — | 阶段 4 | 另行立项 | 分屏、真实思考链 |

合计核心工期约 12.5 个工作日（单人全栈），测试与迁移演练另计 20%。

## 四、测试策略

1. **协议兼容测试**：旧客户端（无新字段）连接新服务端、新客户端连旧快照库，双向回放 `replay_*` 帧不崩。
2. **迁移测试**：构造含 100 会话/500 运行/混合中英文目录名的旧工作区 fixture，跑 0.2 脚本，校验行数守恒 + 抽查内容哈希。
3. **Janitor 安全测试**：热层数据零触碰为红线用例；审计日志与文件系统 diff 对账。
4. **思考链分级快照测试**：同一回合录帧，三档 verbosity 各出一份渲染快照（vitest），防回归。
5. 沿用现有基线命令（含 `PYTHONPATH=` 摘 shim 与项目内 basetemp 的既有坑，见 .workbuddy 记忆）。

## 五、对现有功能的影响汇总

| 变更 | 用户可感影响 | 缓解 |
|---|---|---|
| 归档跨端可见 | 换浏览器归档不再"复活" | 一次性迁移旧 localStorage |
| outputs 目录搬迁 | 会话产物路径变化 | 迁移脚本 + flag 回退 + 旧路径 301 式兜底读取（过渡期 1 个版本） |
| planner 直播剥离正文 | /plan 过程不再出现在正文气泡 | L1 折叠区可展开，调试档完全还原 |
| ToolCard 参数降 L2 | 展开工具卡默认看不到全参数 | 调试档/单卡「显示完整参数」 |
| Scheduler 并入任务中心 | 入口位置变化 | 旧路由重定向 |

无一项删除既有能力；所有行为变化均有开关或迁移期。
