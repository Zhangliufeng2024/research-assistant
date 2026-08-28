# 面板可用性与文件管理评估及重构方案

日期：2026-08-28
范围：前端对话/任务管理面板 + 后端文件与文件夹管理
参考：CodePilot (github.com/op7418/CodePilot)、WorkBuddy、Claude Cowork / Claude Code 系产品的会话与任务管理设计

---

## 第一部分：现状评估结论

### 1.1 前端面板：功能齐全，但"规模一涨就失控"

技术底座是健康的：React 18 + TS + Zustand + 双通道 WebSocket（chat/task），视图懒加载，7 阶段 Timeline + WorkflowPlan + ActivityFeed 的状态展示在同类产品中属于中上水准。问题不在"有没有"，而在"数量增多后的组织方式"。

**评估结论：当对话 > 50、任务历史 > 100 时，会出现明确的可用性塌陷，五个风险全部命中。**

| 风险 | 现状 | 严重度 |
|---|---|---|
| 查找困难 | 会话搜索只匹配标题子串，不搜正文；运行历史 `slice(0,20)` 硬截断、无搜索/筛选/分页；后台任务只显示前 5 条 | ★★★★★ |
| 层级混乱 | 侧栏 6 项中 3 项是聚合组（二级 tab），最深 3 层；会话列表平铺无分组/置顶/星标，只能按 updated_at 排 | ★★★★ |
| 状态不清晰 | `SessionSummary` 无状态字段（运行中靠脉冲圆点暗示）；归档只存 localStorage，换浏览器即丢；Scheduler 触发器的 `enabled` 字段只读不展示、无启停/删除入口 | ★★★★ |
| 切换成本高 | 切换会话不走路由（仅 `/threads/:id` 例外），无法深链/新开/历史前进后退；无 CodePilot 式分屏对照 | ★★★ |
| 上下文断裂 | chatStore 与 taskStore 完全独立：对话不能转任务、任务不回链对话、通知中心有 object_id 但不能跳转 | ★★★★★（最痛的点） |

一句话：**这是"单会话重度使用"设计，不是"多对话多任务并行"设计。** CodePilot 的解法是归档+检查点+分屏+全局 SQLite 检索，WorkBuddy 的解法是专家/空间/连接器分域收纳，本项目目前两者都没有。

### 1.2 后端文件管理：索引优秀，生命周期缺失

存储是"文件系统为事实源 + 双 SQLite 索引"的三层混合：`.ra/platform.sqlite3`（关系态）+ `.ra/sources.sqlite3`（FTS5 全文检索）+ `.ra/sessions/<id>/`（run.json + events.jsonl）+ `writing_outputs/<id>/`（产物）。**索引与检索是项目做得最好的部分**（含 `.ra/changes/index.json` 变更清单、`.sync_manifest.json` 哈希表）。

| 风险 | 现状 | 严重度 |
|---|---|---|
| 命名冲突 | 会话目录 `YYYYMMDD_HHMMSS_slug`，秒级并发可撞名（chat.py 有 `_n` 兜底，pipeline 无）；中文查询 slug 净化后变纯时间戳，目录名不可读 | ★★★ |
| 文件散落 | 同一 session 的状态散在 3 处（run.json、platform.sqlite3、writing_outputs/），删除需双目录 rmtree（chat.py:516），有漏删窗口；仓库根 16 个 `.pytest_tmp*` 残留 | ★★★★ |
| 版本混乱 | 仓库根 4 个顶层状态/计划文档并存（plan260824 / PROJECT_STATUS / CLAUDE / README）；`.ra/changes/` 快照只增不减 | ★★★ |
| 无归档清理 | ✅ 已有：空会话 1h TTL、孤儿回合看门狗、调度器 prune、线程归档。❌ 缺失：`writing_outputs/`、`.ra/changes/`、`events.jsonl` 均无容量上限与轮转 | ★★★★ |

一句话：**"写"的路径设计得好，"死"的路径没人管。** 数据只进不出，半年后的工作区必然膨胀且不可导航。

---

## 第二部分：前端面板重构方案

### 2.1 任务中心信息架构（IA）

把现在的「任务中心」聚合组升级为真正的任务中枢，借鉴 Claude Cowork 的"运行（Run）= 一等公民"模型和 CodePilot 的任务调度器：

```
任务中心（一级侧栏）
├── 进行中    —— 所有 running/paused/awaiting_approval 的 Run，默认落点
├── 看板      —— 按状态分列（新增，见 2.2）
├── 计划      —— 队列 + 定时触发器 + 自动化规则（合并现 SchedulerView）
├── 历史      —— 可搜索/筛选/分页的全部运行记录（替换 slice(0,20)）
└── 通知      —— 迁入，object_id 可点击跳回来源
```

关键决策：**"计划"并入任务中心而非独立页**。Scheduler 现在孤岛化（trigger 不能启停、不能删），并入后复用同一套列表组件和详情抽屉。

### 2.2 任务列表 / 看板组织方式

- **默认列表视图**，列为：状态徽标｜标题（链回来源对话）｜所属项目/空间｜阶段进度条（7 阶段压缩版）｜耗时｜更新时间。支持按状态/项目/时间筛选 + 全文搜索（走 platform.sqlite3，不新造轮子）。
- **看板视图为可选切换**，列 = `queued → running → awaiting_approval → done / failed / cancelled`，卡片拖拽即触发状态操作（如从 awaiting_approval 拖走=快捷批准入口）。WIP 高的用户（批量跑 eval）用看板，普通用户列表即可，不做强制。
- **分组维度**：顶部 Tab 切换「按状态 / 按项目 / 按来源对话」三种透视，对应 WorkBuddy 的分域收纳思路。

### 2.3 自动化工作流的呈现形式

现状的 SchedulerView 是"工程师视角"（interval_seconds 裸字段）。改为**规则卡片**：

- 每张卡片一句话描述规则：「每 2 小时 · 运行 xxx 工作流 · 下次 14:00」，配启停开关、最近 5 次运行结果迷你条（绿/红点序列）、编辑/删除。
- 触发器与队列任务在同页上下分区，触发器卡片点击展开其派生的运行历史（父子关系可视化）。
- 支持 cron + 间隔双模式（对齐 CodePilot），UI 上间隔模式用自然语言输入（"每天早上 9 点" → rrule/cron）。

### 2.4 任务状态流转展示

保留现有 Timeline + ActivityFeed（这是优势，不动），补三块：

1. **状态机显式化**：在任务详情头部画一条横向状态带 `queued → running → (awaiting_approval ⇄ running) → done/failed/cancelled`，当前节点高亮，失败节点可点击直接跳到 ActivityFeed 对应错误行。
2. **列表级状态一致性**：把 `TaskPhase` 与 `RUN_STATUS_LABEL` 收敛为同一枚举同一文案（现状 running/complete/failed/cancelled/legacy 与 idle/running/done/failed/error/cancelled 两套并存，`legacy` 这种兜底态不应出现在 UI）。
3. **等待批准作为独立状态上列表**（现在埋在详情里），因为人工审批是唯一的"需要用户行动"状态，值得全局红点。

### 2.5 对话与任务的关联管理（本次重构的核心）

模型层改动最小、收益最大的一项：

- **数据模型**：`RunSummary` 增加 `source_session_id`；`SessionSummary` 增加 `derived_run_count`、`pinned`、`archived`（归档从 localStorage 迁入 platform.sqlite3，解决换浏览器丢失）。
- **双向互链**：
  - 对话内：消息工具条加「转为任务」（把当前对话上下文打包为新 Run 的 prompt + outputs_dir）；
  - 任务详情：顶部显示来源对话卡片，点击回跳 `/chat?session=<id>`；
  - 会话列表项：有派生任务的显示任务徽标（●3），点击内联展开任务子列表。
- **路由化会话**：`/chat/:sessionId` 入路由（保留无 id 的 `/chat` 为新会话），获得深链、浏览器前进后退、通知跳转三合一收益。
- **会话列表分组**：置顶区（pinned）→ 今天 → 本周 → 更早 → 已归档，参考 WorkBuddy/ChatGPT 系的时间分组，成本极低、收益即显。

### 2.6 前端改动范围与优先级

| 优先级 | 项 | 改动范围 | 对现有功能影响 |
|---|---|---|---|
| P0 | 对话↔任务互链（source_session_id + 双向跳转） | 2 个 store、SessionList、TasksView 详情头、协议类型 | 纯增量，无破坏性 |
| P0 | 归档入 SQLite + 会话时间分组 + pinned | SessionList、sessionArchive.ts 废弃、platform_store 加列 | 归档行为变化（跨端可见），需一次性迁移 localStorage |
| P1 | `/chat/:sessionId` 路由化 + 通知跳转 | App.tsx、ChatView、NotificationsView | URL 结构新增，旧链接兼容 |
| P1 | 历史运行搜索/筛选/分页 + Scheduler 启停删除 | TasksView、SchedulerView、对应 API | 纯增量 |
| P2 | 看板视图 + 状态机显式化 + 触发器规则卡片 | 新组件 KanbanBoard、StatusStrip | 新增视图，默认不变 |
| P3 | 分屏对照（CodePilot 式） | ChatView 布局 | 大改，建议独立迭代 |

---

## 第三部分：后端文件与文件夹管理架构方案

### 3.1 目录结构规范

核心原则：**一个会话 = 一个自包含目录**，消除当前"同一 session 散三处"的双写/漏删窗口。

```
<工作区>/
├── .ra/                          # 运行时状态（不进 git，已有）
│   ├── platform.sqlite3          # 关系索引（保留）
│   ├── sources.sqlite3           # FTS5 检索（保留）
│   ├── sessions/<session_id>/    # run.json + events.jsonl + chat.json（保留）
│   ├── outputs/<session_id>/     # 【迁移】产物并入 .ra，会话即目录
│   │   ├── uploads/
│   │   ├── artifacts/            # 正式产物（docx/pptx/html）
│   │   └── drafts/               # 中间稿，可安全清理
│   └── changes/                  # 变更快照（加容量策略，见 3.4）
├── docs/
│   └── plans/YYYYMMDD-*.md       # 计划文档统一日期前缀（已有惯例，强制执行）
├── eval/
│   ├── golden_tasks/             # 输入（保留）
│   └── results/YYYYMMDD_HHMMSS/  # 评估输出按运行批次归档
└── tmp/                          # 【新增】一切临时物的唯一出口
    └── pytest/                   # 替代仓库根 16 个 .pytest_tmp*
```

迁移要点：`writing_outputs/<id>/` → `.ra/outputs/<id>/`，`SessionSummary.outputs_dir` 指向新位置；删除会话从"双 rmtree"变"单 rmtree"，原子性提升。

### 3.2 命名规则

1. **session_id 加随机后缀**：`YYYYMMDD_HHMMSS_<slug>_<rand4>`（如 `20260828_091530_energy_shap_a3f9`），根治秒级撞名，`_n` 兜底逻辑可删。
2. **slug 保中文**：净化规则从"全下划线化"改为"保留 CJK 字符 + 连字符分词"（`能耗-SHAP分析-a3f9`），目录名恢复可读。
3. **版本命名禁词**：禁止 `final/final2/v2_new/backup` 进文件名；版本迭代一律走 `.ra/changes/` 快照，文件名保持稳定。计划/状态文档只留 `docs/plans/` 下日期前缀一种形态，仓库根的 `plan260824.md` 迁入。
4. **临时文件**：agent 草稿 `_ra_exec_*.py`、pytest 产物全部落 `tmp/`，gitignore 收敛为 `tmp/` 一条规则，替代现在的逐条兜底。

### 3.3 索引与检索机制

保留现有三索引（platform / sources-FTS5 / changes-manifest），补两件事：

- **manifest.json 进会话目录**：每个 `.ra/outputs/<id>/` 下生成 `manifest.json`（产物清单：文件名/类型/大小/生成时间/对应 run_id），平台库加 `artifacts` 表做二级索引。收益：前端"资料库"页可以脱离文件系统扫描直接渲染，也为全文检索产物铺路。
- **统一查询入口**：`PlatformStore` 增加 `search(query, scope=session|task|artifact)` 单方法，前端 WorkspaceSearch（Ctrl+K）和历史页共用，避免各处自写 LIKE。

### 3.4 归档与清理策略

分层 TTL，全部可配置，默认保守：

| 层 | 对象 | 策略（默认） |
|---|---|---|
| 热层 | 运行中/近 7 天会话 | 不碰 |
| 温层 | 30 天未动的会话 | 状态标记 archived（列表折叠），文件不动 |
| 冷层 | 90 天未动且已归档 | `events.jsonl` gzip 压缩；`drafts/` 删除，`artifacts/` 保留 |
| 快照 | `.ra/changes/` | 每会话保留最近 50 个快照，总量上限 500MB，超出 LRU 淘汰 |
| 日志 | events.jsonl | 单文件 10MB 轮转，最多 3 代 |
| 临时 | `tmp/` | 启动时清理 7 天前内容 |

执行方式：复用现有 `_sweep_zero_turn_sessions` 的看门狗模式，扩展为统一 `Janitor` 周期任务（挂在 scheduler.py 上），**所有删除先写审计日志**（删了什么、何时、依据哪条策略），符合"清理前可追溯"的要求。

### 3.5 后端改动范围与优先级

| 优先级 | 项 | 改动范围 | 对现有功能影响 |
|---|---|---|---|
| P0 | session_id 随机后缀 + slug 保中文 | config.py、chat.py | 新会话生效，旧目录不动 |
| P1 | outputs 并入 .ra + 单 rmtree 删除 | chat.py:79/281/516、web/workspace.py、迁移脚本 | **有迁移成本**：需一次性搬迁存量 writing_outputs/ 并更新 outputs_dir |
| P1 | Janitor 统一清理（温/冷层 + changes LRU + tmp） | scheduler.py、platform_store.py | 默认只动 archived 数据，热数据零影响 |
| P2 | manifest.json + artifacts 表 + 统一 search() | platform_store.py（SCHEMA_VERSION 10→11）、资料库 API | 增量迁移，旧库自动升级 |
| P2 | 仓库根卫生（.pytest_tmp* 清除、plan 文档归位、.spec 矛盾修正） | .gitignore、目录搬迁 | 仓库级，无运行时影响 |

---

## 附：与参考项目的对照速查

| 能力 | CodePilot | WorkBuddy | 本项目现状 | 本方案 |
|---|---|---|---|---|
| 会话归档 | ✅ 持久化 | ✅ | ⚠️ 仅 localStorage | ✅ 入 SQLite（P0） |
| 会话↔任务关联 | 检查点 rewind | 专家/空间分域 | ❌ 零关联 | ✅ 双向互链（P0） |
| 任务调度 | cron+间隔 | rrule 自动化 | ⚠️ 孤岛页 | ✅ 并入任务中心（P1） |
| 审批状态 | per-action approval | ✅ | 埋在详情 | ✅ 全局状态（P2） |
| 文件生命周期 | SQLite WAL 单库 | 云侧管理 | ❌ 只进不出 | ✅ 分层 TTL（P1） |
| 产物索引 | 文件树+预览 | 资料库 | ⚠️ 半套 | ✅ manifest 补齐（P2） |
