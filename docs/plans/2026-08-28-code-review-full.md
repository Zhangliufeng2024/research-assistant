# research-assistant-v3 全面代码质量评估

日期：2026-08-28 · 版本 v3.5.0（commit `abf29c1`）
方法：全量静态审查 + 关键结论逐条源码复核 + 外部事实联网核验
范围：后端 22,221 行 / 前端 14,343 行 / 测试 15,371 行

> **与既有文档的关系**：`2026-08-28-panel-and-storage-refactor-assessment.md` 已从
> **UX 与生命周期**角度评估过面板与文件管理（R17 已按该方案落地）。本文聚焦它
> **未覆盖**的层面：**并发安全、Agent 内核正确性、能力差距对照、以及可复现的真实缺陷**。
> 两者互补，不重复。

---

## 0. 总体结论

| 维度 | 评级 | 说明 |
|---|---|---|
| 架构设计 | **A-** | 分层清晰，机制层（状态机/门禁/事件总线/预算）是真实代码而非提示词 |
| 工程质量 | **B+** | CI 齐全、测试量大、ruff/tsc 干净；但函数过长、异常静默吞掉 |
| 并发正确性 | **C** | 解耦设计优秀，但多处"无锁 + 依赖恰好原子"，存在确定性竞态 |
| 文件治理 | **C+** | 索引与检索强，但 6 套并行真相，版本化覆盖不全，恢复功能会删数据 |
| 前端完成度 | **B+** | 16 个 view 无空壳，流式/重连/真替换等体验细节高于同类 |
| Agent 能力完备度 | **C+** | 编排/预算/审批/崩溃恢复达标；记忆、MCP、沙箱、多模态、fallback 缺失 |
| **生产可用性** | **⚠️ 阻塞** | **存在 1 个首日即崩的 P0**（见 §6.1） |

**一句话**：这是一个**工程纪律远超平均水准**的项目——机制层扎实、测试充分、对自己的边界
诚实（代码注释里多处主动标注"这不是沙箱"）。但它目前是**"单会话重度使用"设计**，
在并发正确性、能力完备度和文件生命周期三方面存在结构性缺口，且有一个会让新用户
**第一通请求就失败**的模型兼容性缺陷。

---

## 1. 值得肯定的核心资产（重构时务必保留）

这些是达到或超过业界水准的实现，不要在重构中丢弃：

1. **回合↔连接解耦**（`web/chat.py:1094-1134` `_TurnHandle`）—— 回合状态与 WebSocket
   对象零引用关系，帧发射按 sid 现查 `_SINKS`（`:1449-1460`）而非闭包绑定。断连不取消生成，
   这是结构性设计而非补丁，多数同类产品未做到。
2. **两阶段 LLM 看门狗**（`agent.py:208-243`）—— 首字节窗 / 静默窗 / 单次尝试墙钟三层，
   `asyncio.shield` + 显式 cancel 收尾，监督粒度是**每次尝试**而非整个重试循环。
3. **上下文压缩的配对安全性**（`kernel/context.py:144-170`）—— 逐行验证过：回退切点
   保证了 `tool_use`/`tool_result` 配对完整，插入/替换的偏移与账本净增量一致。
   这是 agent 循环里最容易出错、也最致命的一处，本项目做对了。
4. **持久化队列的租约语义**（`runtime/scheduler.py:181-220`）—— 丢租约即取消本地执行
   且**绝不回写结果**（`:215-220`），配合租约续期与过期恢复，崩溃语义清晰。
5. **预算三层聚合**（`kernel/budget.py` + `workflows/registry.py:32-48`）—— 角色级/节点级/
   全局级取交集，摘要调用也计量（修掉了绕过预算的常见漏洞）。`reserve()` 超限直接 raise，
   是**真硬闸**。
6. **审批失败即拒**（`kernel/approval.py:53-73`）—— 无 approver / 超时 / approver 异常
   一律 deny，默认安全。
7. **CI 矩阵**（`.github/workflows/ci.yml`）—— ruff + pytest（ubuntu/windows × 3.10/3.12）
   + tsc + vitest + vite build，前端后端都覆盖。

---

## 2. 问题一：前端面板分区是否合理？与 WorkBuddy / Claude Cowork 的差距

### 2.1 现状

```
Shell: Sidebar(w-60) + main(flex-1)          ← 外层恒 2 栏
/chat 时: 会话列表(w-60) + 对话列 + 产物 dock(w-72)   ← 仅此时 3 栏（可再加分屏成 4 栏）
```

- **路由 15 个 / 侧栏 6 项 / 3 个聚合组**（`navModel.ts:100-137` 前缀规则，纯函数 + 单测）
- 侧栏：总览 · 会话 · 任务中心 · 研究工作台 · 资料库 · 设置
- 二级 tab：任务中心 = 进行中/看板/计划/历史/通知/分析运行

### 2.2 分区合理性判定：**基本合理，两处失分**

**合理之处**：`navModel.ts` 用纯函数 + 单测做分组判定，质量高于平均；功能域划分
（对话 / 任务 / 研究 / 资料 / 设置）语义无重叠。

**失分点**：
1. `/notifications` 被塞进「任务中心」组（`navModel.ts:41`）——通知是横切关注点，
   不该是任务的第六个 tab。顶栏虽有铃铛（`WorkspaceSearch.tsx:24-45`），点进去仍落回任务组。
2. **无"项目/工作区"这一层**。左栏第一层是功能域，项目切换藏在总览页一个 `<select>`
   里，且选中后 `window.location.reload()` 整页刷新（`ProjectHomeView.tsx:56`）。

### 2.3 完成度核验：**16 个 view 全部是真实现，无空壳**

这一点与"文件只有 20 行"的表象相反——它们是**手工压成单行 JSX**：

| 文件 | 行数 | 最长行字符数 | 判定 |
|---|---|---|---|
| `ArtifactReviewView.tsx` | 21 | **4,344** | 真实现（预览+diff+provenance+门禁+三动作） |
| `AnalysisRunsView.tsx` | 20 | **3,652** | 真实现（四面板+复现+双运行比对） |
| `NotificationsView.tsx` | 28 | 1,881 | 真实现（含 objectLink 回跳） |
| `ResearchView.tsx` | 66 | 1,507 | 真实现（6 统计卡+证据矩阵+决策日志） |

唯一的 stub 是 `views/Placeholder.tsx`，且**无任何路由引用**——死代码。

> ⚠️ 但这本身是可维护性问题：4,344 字符的单行 JSX 无法 review、无法 diff、无法定位报错。
> 建议后续拆分为正常组件。

### 2.4 与 WorkBuddy / Claude Cowork 的差距

| 能力 | 本项目 | 证据 |
|---|---|---|
| 三栏（导航-对话-产物） | **仅 /chat 内成立** | `App.tsx:64-95` 外层恒 2 栏 |
| 主对话区常驻 | ❌ 切路由即卸载（**但 WS 与 store 是模块级单例，流式不中断**） | `ws.ts:8,14`、`chatStore.ts:322` |
| 项目/工作区切换层 | ❌ 总览页 select + 整页 reload | `ProjectHomeView.tsx:56` |
| MCP / connector UI | ❌ 前端零入口（grep `mcp`/`connector` 无命中） | — |
| 全局命令面板 | ⚠️ 有 Cmd+K 但**只是搜索跳转，不能执行动作** | `WorkspaceSearch.tsx:56-66` |
| 多会话并行/多标签 | ❌ 单活跃会话；分屏是**只读**第二会话（20s 轮询快照） | `ChatView.tsx:533-543` |
| 交互式 todo 面板 | ❌ 计划一次性生成、人不可编辑，无 TodoWrite 类工具 | `tools/registry.py:22-292` |
| 终端面板 | ❌ 有 bash 工具卡，无嵌入式交互终端 | — |
| Checkpointer / 时间旅行 | ❌ 编辑重发是**真替换**（破坏性），无快照回退 | `chatStore.ts:469-549` |
| 权限模式快捷切换 | ❌ 只能写 .env 表单，对话中无切换 | `SettingsView.tsx:503,509` |
| 响应式/移动端 | ❌ 硬编码桌面，窄屏会话列表与产物 dock **直接消失且无抽屉兜底** | `ChatView.tsx:285,325,546` |
| 快捷键体系 | ⚠️ 仅 Cmd+K 与 Esc 栈两处 | `WorkspaceSearch.tsx:64`、`useEscapeStack.ts:46` |
| 主题切换 / 通知中心 / Agent roster | ✅ 都有 | `useTheme.ts`、`NotificationsView.tsx`、`AgentPanel.tsx` |

**三个最该补的结构性差距**（按影响排序）：
1. **项目/工作区层**（决定能否多项目并行）
2. **主对话区常驻**（决定能否边跑任务边对话）
3. **MCP/connector**（决定工具生态能否扩展）

---

## 3. 问题二：线程管理与文件统一管理

### 3.1 会话线程管理：**设计优秀，但有 3 处确定性缺陷**

**优秀部分**（已逐行验证，见 §1）：
`_TurnHandle` 解耦、孤儿看门狗（`chat.py:1147-1165`，900s 宽限 → 协作停止 → 30s 硬取消）、
帧环形缓冲 + 会话内单调 seq 续播（`chat.py:1126-1134, 1625-1627`）、取消路径穿透到
LLM 调用（`agent.py:250-274`）。

**缺陷 1（P1）— 重复 attach 永久污染观察者计数**
```python
# chat.py:1479-1487 _observe：observers 无条件 +1，watching 有条件 append
handle.observers += 1
if handle not in watching:
    watching.append(handle)
# chat.py:1462-1467 _release：以 watching 为准，不在其中直接 return
if handle not in watching: return
```
`chat.py:1984` 明明检测到 `already = target in watching`，却**只打日志仍继续 +1**。
→ 断连重连后 `observers` 停在 1 → **孤儿看门狗永不武装** → 无人观察的回合一直跑到预算耗尽。
网络抖动场景下高度可达。**修复**：`if already: return`。

**缺陷 2（P1）— `_LIVE`/`_SINKS` 注册竞态**
```python
# chat.py:1547-1558
await previous.close(code=4001, ...)   # ← 挂起点
_LIVE[sid] = websocket
_SINKS[sid] = sink_fn
```
两条新连接并发进入时，`await close()` 让出后相互覆盖，导致**某条活跃连接不在 `_SINKS` 里**，
其帧被投递到另一条连接——一个会话的输出会串到另一个标签页。三张表**无任何锁或原子占位**。
`chat.py:1099-1100` 声称"不需要锁"的论证在多连接前提下不成立。

**缺陷 3（P1）— `BackgroundTaskHub.handles` 永不清理（确定性内存泄漏）**
```
task_hub.py:74   self.handles: dict[str, TaskHandle] = {}
task_hub.py:90   self.handles[task_id] = handle
task_hub.py:215/249/259/264/274/281/293   ← 全是 .get()，全文件无 pop/del
```
`_drive` 的 `finally`（`:172-210`）落库、发通知、收尾步骤，唯独不摘 handle。
长驻桌面进程每跑一个任务泄漏一条（含 `subscribers` set、队列、Task 引用），
且 `routes.py:188-190` 的 `live_count` 会随时间虚高。

**其他**：chat 出站队列**无界**（`chat.py:1406`），与任务侧 `maxsize=1000`
（`task_hub.py:218-224`）口径不一致；并发会话数**无任何准入上限**；
`_SESSIONS` 每会话常驻最多 4000 帧缓冲且无 LRU/TTL（`chat.py:1140, 1954`）。

### 3.2 两套体系：任务已统一，会话没有

`platform_store.py` 的 Thread/Turn/AgentItem 只有**后台任务**在写（`task_hub.py:112-120`
兼容桥）。聊天会话走**文件系统** `SessionStore`（run.json + events.jsonl + history.json），
仅向 platform_store 读写 pinned/archived 标志。

> `PROJECT_STATUS.md:33` 称"durable task 会自动映射到统一线程时间线"——
> **仅对任务成立，对会话不成立**。会话与任务是两套独立状态机，互不可见。

### 3.3 后台任务管理：**质量良好**

状态机完备、租约实现完整、`RA_SCHEDULER_CONCURRENCY` 真实生效（`scheduler.py:48-62`）、
资源槽位争用走 `defer_job` 且**不消耗重试预算**（`:164-177`，是真正的背压）。

**缺口**：
- `tasks` 表 UPDATE **无前置状态校验、无 CAS**（`platform_store.py:794-822`），
  `complete` 可覆盖 `complete`、`running` 可回退 `queued`。当前靠"调用点无 await 交错"侥幸安全。
- `BEGIN IMMEDIATE` 只用在 4 处，**`complete_job`/`fail_job`/`defer_job`/`recover_expired_jobs`
  未用**。其中 `fail_job` 是典型的先 SELECT 后 UPDATE（`:2016-2029`），多 worker 下会抛
  `SQLITE_BUSY_SNAPSHOT` 且**无重试层** → 丢一次状态转换。
- `mark_orphaned_running_tasks` 只动 `tasks` 表不动 `job_queue`，二者恢复窗口不一致。
- 作业级**无检查点**，租约过期后从零重跑（工作流内部有节点级 checkpoint，但
  paper/single 路径没有）。

### 3.4 文件统一管理：**没有统一管理，存在 6 套并行真相**

| # | 存储 | 覆盖范围 | 是否权威 |
|---|---|---|---|
| 1 | `.ra/changes/index.json` | 仅被版本化的工具写入 | 否（漏网多） |
| 2 | `platform_store.artifacts` 表 | 由 `chat.py:650` **拉模式**回填（有人调 REST 才更新） | 否 |
| 3 | `outputs/<sid>/manifest.json` | 磁盘副本，**截断 500 条**（`chat.py:584`） | 否（超限即与 2 不一致） |
| 4 | `artifact_reviews` 表 | 任务模式，**仅 complete/failed 时索引**（cancelled 永不索引） | 否 |
| 5 | `<out>/.ra/artifacts/manifest.json` | 任务模式第二套，与 4 **互不通信** | 否 |
| 6 | 前端启发式扫描 | `file_ops.py:128` 注释自承"供前端 files 启发式定位" | 否 |

**版本化真实覆盖率远低于声称。** `PROJECT_STATUS.md:336` 称"bash/run_python 的间接
新增、修改、删除也记录进可恢复变更历史"，实际：

- 生产代码中 `version_store.record()` **只有两个调用点**，都在 `registry.py:613,635`
- 快照根**只有 `write_anchor` 一个目录**（`registry.py:488,510,536`）——
  脚本用绝对路径或 `../` 写到别处 → **静默漏网**
- `.ra` 整个被排除、`_ra_exec_*.py` 被名字排除
- subprocess 路径（`routes.py:1136` 复现分析、skill 脚本）**零覆盖**
- 超限**静默丢弃**：512 文件 / 32MB 到顶后 `return`/`continue`（`registry.py:384,393`），
  无日志、回执也不提示丢弃数量

**【P0】恢复功能会删数据**（已复核确认）：
```python
# versioning.py:98-106
data = self._snapshot(change_id, side)          # :77 文件不存在返回 None
if data is None:
    if target.exists():
        target.unlink()                          # ← 快照丢了就删文件！
```
```python
# janitor.py:180-187 —— 淘汰 bin 时只 unlink 文件，index.json 记录留成悬空
path.unlink()
```
**组合后果**：`.ra/changes` 超 500MB → 最旧 `before.bin`/`after.bin` 被删 →
UI 仍显示该条记录（index.json 未清理）→ 点"恢复" → `_snapshot` 返回 None →
**目标文件被删除**。恢复按钮变成销毁按钮。

**路径围栏有一处真实缺口**：`write_file` 只 `safe_resolve` 到**父目录**就把文件名裸拼回去
（`file_ops.py:148-150`），而 read/edit/glob/grep 都对**完整路径** resolve。
工作区内一个指向 `.env` 的符号链接会被 `write_file` 写穿。读写口径不一致证明这是遗漏。

**清理面缺失**：`.ra/tool_outputs/` 无清理、`janitor_audit.jsonl` 无轮转、
孤儿 `outputs/<sid>` 明确保留不清理（`chat.py:403-404`，会无限增长）。

---

## 4. 问题三：Agent 能力差距全景

逐项 grep + 读码验证（18 项）：

| # | 能力 | 结论 | 差距 |
|---|---|---|---|
| 1 | 规划 | 部分 | 有持久化 DAG + plan.json 续跑，但**无交互式 todo 工具** |
| 2 | 反思纠错 | 部分 | 门禁真驱动返工（≤3 轮，`runner.py:492`），但全是规则检查、**无 LLM-as-judge** |
| 3 | **记忆体系** | **无** | grep `memory/profile/preference` 在后端**零命中**；无跨会话记忆、无用户画像 |
| 4 | 多 Agent 编排 | 有 | Semaphore + gather 真并行，角色策略完善；但**仅靠文本/文件通信**，无消息总线 |
| 5 | **工具生态** | 部分 | 技能是可执行代码（非纯提示词），有 `ToolExtension` 扩展点；但**无 MCP**、无热加载 |
| 6 | 上下文工程 | 部分 | 压缩扎实；但**无 rerank**，向量是 128 维 hashing trick（`sources.py:31-39`）非模型 |
| 7 | **可靠性** | 部分 | 重试/看门狗/幂等强；但**无模型 fallback**（`factory.py` 只能二选一，失败即失败） |
| 8 | **可观测性** | 部分 | 有 events.jsonl + 调试 UI；但**无 tracing/span、日志非结构化** |
| 9 | 评估体系 | 部分 | 3 个 golden task，代码可用且注释写 "suitable for CI"；但 **CI 不跑**（无回归基线） |
| 10 | 权限协同 | **有** | 审批闭环 + 失败即拒，代码诚实标注"这不是沙箱" |
| 11 | **多模态** | **无** | 附件链路完整，但 `_content_for_llm`（`chat.py:1168-1187`）**降级为路径文本**；LLM 层 grep `image/vision/base64` 零命中 |
| 12 | 协作导出 | 部分 | 有 zip 导出；**无分享、无鉴权、无协作** |
| 13 | 知识接入 | 部分 | RAG + 抓取 + Crossref/S2/OpenAlex 齐备；**无 connector** |
| 14 | 调度 | 部分 | 队列/租约/崩溃恢复成熟；**仅 interval，无 cron/rrule**（`platform_store.py:2184-2196`） |
| 15 | 成本控制 | **有** | 四维预算三层聚合，业界对齐 |
| 16 | **沙箱隔离** | **无** | 见 §5 |
| 17 | 多租户 | 部分 | 多项目规范（project_id 外键 + 级联）；**无用户/鉴权/租户** |
| 18 | 遥测上报 | 无 | 无 Sentry 类上报（本地优先场景下属合理取舍） |

---

## 5. 安全性

**做得对的**：
- 设置 API `GET` 不回明文（`settings.py:250,304-306`）
- `build.py:175-204, 365-367` 扫 `.env` 与产物字节级密钥
- `.env` 从未入 git（`git log --all -- .env` 为空）；全仓被跟踪文件无真实密钥
- 项目对自身边界**诚实**：`permissions.py:9-10` 明写 "not sandboxing"；
  `exec_provider.py:6-7` 明写容器 provider 是"documented extension point"

**问题**：
1. **【P0】run_python 完整继承环境变量** —— `python_exec.py:54` `child_env = {**os.environ, ...}`，
   模型生成的代码 `os.environ["LLM_API_KEY"]` 即可读取全部密钥。
   （复核更正：冻结态 `run_python_inprocess` **不是**进程内执行，而是
   `multiprocessing` **spawn 子进程**（`frozen_exec.py:139-145`），名称有误导性；
   但子进程同样继承父进程环境，风险等级不变。）
2. **【P0】bash 是无限制系统 shell**（`bash.py:243-245`）—— 路径围栏对命令本身无效，
   `type %APPDATA%\...\.env` 一行读走全部密钥。
3. **【P1】提示词注入零防护** —— 工具结果原样拼进 messages（`agent.py:747-755`），
   无标签包裹、无来源标注、无清洗。结合上两条，一次注入即可外传密钥。
4. **【P1】危险命令正则过窄**（`permissions.py:22-43`，仅 17 条且多带尾锚）——
   `rm -rf /tmp/data`、`del /s /q D:\data`、`git clean -fdx`、`taskkill`、
   `Invoke-Expression` 等**全部放行**。
5. `timeout` 后 `proc.kill()` 只杀直接子进程，代码内派生的孙进程不被回收。

---

## 6. 缺陷清单（按优先级，均已复核）

### 6.1 【P0】Anthropic 默认路径必然 400 —— 新用户首日即崩

**已联网核实**（Anthropic 2026-08 官方参数弃用表 + 第三方实测）：

> temperature / top_p / top_k 在 **Claude Opus 4.7 及之后、以及全部 Claude 5 系列**
> （opus-5 / sonnet-5 / fable-5）传**非默认值即返回 HTTP 400**。

而本仓库：
```python
constants.py:17   DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"    # ← 正是 Claude 5 系列
agent.py:97       temperature: float = 0.5                        # ← 非默认
anthropic.py:164  temperature: float = 0.7                        # ← 非默认
anthropic.py:183  "temperature": temperature,                     # ← 无条件发送
```
**全仓 grep `claude-sonnet-5|adaptive|effort` 无任何模型守卫**（仅有 constants 的定义本身）。

**后果**：新用户只填 Anthropic API Key、不指定模型 → **每一通请求都 400** →
表现为永久"思考中"或连接失败。这是**首次运行即阻断**级别。

**连带影响（同一根因）**：
- `kernel/context.py:31` `("claude-sonnet", 200_000)` —— Sonnet 5 实为 **1,000,000**
  （联网核实），压缩在 140k 就触发，**浪费 86% 上下文窗口**；Opus 5 同为 1M。
- `budget.py:28` `claude-opus: 15.0/75.0` —— Opus 5 实为 **$5/$25**，成本显示 **3 倍高估**；
  无 `claude-fable` 条目（未知模型 → `cost_cap_enforceable=False`，成本上限静默失效）。
  （Sonnet 3.0/15.0 将于 9/1 起为标准价，此项基本正确。）
- Sonnet 5 自适应思考默认开启 + 新分词器（约多 30% token），`max_tokens=16384` 截断风险上升。

**修复**：按模型族判断是否下发 temperature；更新窗口表与价格表；为未知模型给出显式告警。

### 6.2 【P0】前端无限请求循环

```tsx
// ProjectHomeView.tsx:33-46
const refresh = useCallback(() => api.get("/api/project/home").then(setHome)..., []);
useEffect(() => {
  void refresh(); ...
}, [refresh, refreshApprovals, home?.project]);   // ← home 每次都是新对象
```
`refresh()` → `setHome(新对象)` → `home?.project` 引用变化 → effect 重跑 → 再 `refresh()`。
**落地页以网络速度无限轮询 `/api/project/home`。**
修复：把 recentProjects 逻辑拆到独立 effect，依赖 `home?.project?.root`（字符串）而非对象。

### 6.3 【P0】恢复按钮删除文件 —— 见 §3.4 末段

`versioning.py:104-106` + `janitor.py:185`。修复：`data is None` 时改抛异常；
淘汰 bin 与移除 index 记录必须在同一事务。

### 6.4 【P1】清单

| 问题 | 位置 |
|---|---|
| 重复 attach 抬高 observers，看门狗失效 | `chat.py:1984, 1484, 1462-1467` |
| `_LIVE`/`_SINKS` 注册竞态，帧串投 | `chat.py:1547-1558` |
| `_start_turn` 无 `_ACTIVE` 占位检查，可产生并发回合 | `chat.py:1953` |
| `handles` 永不清理（内存泄漏） | `task_hub.py:74-293` |
| `write_file` 符号链接写穿围栏 | `file_ops.py:148-150` |
| 四个写方法缺 `BEGIN IMMEDIATE`（多 worker 丢状态转换） | `platform_store.py` complete/fail/defer/recover |
| chat 出站队列无界 | `chat.py:1406` |
| 无 ErrorBoundary，任一 view 报错白屏 | `App.tsx`（grep 零命中） |
| 版本化未下沉到 `atomic_write_text`，subprocess 路径零覆盖 | `core.py:33` |
| OpenAI 侧 cache token 完全不计量 | `openai_compat.py:219, 323-327` |
| 危险命令正则过窄 | `permissions.py:22-43` |
| 超时后孙进程不回收 | `frozen_exec.py:145-149` |

### 6.5 代码质量指标（AST 实测 40 文件 / 327 函数）

| 指标 | 数值 |
|---|---|
| 参数类型注解率 | **50.5%** |
| docstring 覆盖率 | **56.3%** |
| 裸 `except:` | **0 处** ✅ |
| `except Exception` + `pass` | **约 60 处**（静默吞异常） |

**超长函数**：`agent.py:277 run_agent()` **555 行 CC=89**、`pipeline/runner.py:150` 430 行
CC=74、`cli.py:65 main()` 391 行 CC=85、`api.py:82` 276 行、`tools/registry.py:460 execute()`
161 行 CC=49。

**重复代码块**：截断逻辑三处一字不差（`bash.py:266`、`python_exec.py:83`、`frozen_exec.py:169`）；
`stop_reason_map` 四处重复；steer 注入三处重复；`registry.py:528` 是死代码。

---

## 7. 仓库与工程卫生

- **CI 存在且合理**（`.github/workflows/ci.yml`）：ruff + pytest（双 OS × 双 Python）
  + tsc + vitest + build。**缺 eval**（合理，需 API key）与覆盖率统计。
- **测试规模大但需警惕假绿**：15,371 行后端 + 前端单测。`PROJECT_STATUS` 已记录教训——
  "mock 掉 ws 层的 vitest 与裸 websocket 的后端 E2E 对前端状态机 bug 完全盲，R7~R9 三轮逃逸"，
  故已引入真实浏览器 E2E（`scripts/e2e_*.py`）。这是正确的方向，建议把 E2E 也纳入 CI。
- **仓库卫生差**（已复核）：
  - 未跟踪：`git_diag.txt` / `git_diag_utf8.txt` / `git_diag_done.txt` / `audit_result.txt`
  - `.audit_tmp/`（含 `outside-*/secret.txt` 等越权测试样本）**不在 `.gitignore`**
  - 7 个 `.pytest_tmp_*` 共约 **176MB**（`.gitignore:84` 已忽略，但磁盘持续增长）
  - `dist/` 246MB（4~5 个历史安装包）、`build/` 77MB、`node_modules/` 135MB
- **文档**：`docs/protocol.md` 45KB（契约详尽）+ `USER_GUIDE.md` + 12 份 plan，
  文档密度高；但 `README.md:32,182` 与 `PROJECT_STATUS.md:336` 存在**声称超前于实现**的情况。

---

## 8. 建议：如果只做 8 件事

按「影响 × 成本」排序，前 4 项建议一周内完成：

| # | 事项 | 工作量 | 理由 |
|---|---|---|---|
| 1 | **修 Anthropic temperature 守卫** + 更新窗口表/价格表 | 半天 | 当前新用户 100% 失败 |
| 2 | **修 ProjectHomeView 无限轮询** + 补 ErrorBoundary | 1 小时 | 落地页持续打爆后端 |
| 3 | **恢复功能改抛异常** + 淘汰 bin 同步清索引 | 2 小时 | 当前是数据销毁按钮 |
| 4 | **`handles.pop`** + `if already: return` + `_ACTIVE` 占位检查 | 2 小时 | 三处一行/三行修复，消除确定性泄漏与竞态 |
| 5 | **版本化下沉到 `atomic_write_text`**，subprocess 路径纳入 | 1 天 | 让"统一管理"名副其实 |
| 6 | **bash/run_python 环境净化**（剔除密钥变量）+ 危险命令正则扩充 | 1 天 | 密钥可被模型一行读走 |
| 7 | **MCP 客户端** | 1~2 周 | 一次投入同时解锁工具生态与 connector |
| 8 | **跨会话记忆**（SQLite 已就绪，加表 + 工具） | 3~5 天 | 让产品"越用越懂你" |

**不建议近期做**：重写前端（16 个 view 无空壳，收益低）；
自建 connector（先有 MCP）；真容器沙箱（桌面单机场景，先做环境净化即可）。

---

*本文所有结论均附源码位置并经二次复核；外部事实（Claude 5 参数弃用、模型 ID、
上下文窗口、价格）经 2026-08-28 联网核实。与既有评估文档互补。*
