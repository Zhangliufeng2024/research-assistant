# 代码审阅报告 — research-assistant v3.6.0

> 审阅日期：2026-08-31 · 审阅范围：全量源码（后端 79 个 .py / 24,845 行，前端 79 个非测试 .ts/.tsx，共约 34k 行）
> 基线状态：`import research_assistant` OK（3.6.0）· `compileall` 全绿 · `tsc --noEmit` 全绿 · 941 Python + 213 Vitest 通过
> 标注约定：`[路径:行号]` 均为实际读到的位置；每条只记录**在代码中确实看到**的问题。

---

## 0. 总体判断

这是一个**机制密度明显高于同类个人项目**的工程：状态机、质量门禁、Hook 总线、预算守卫、DAG 指标、产物版本化、断线回放，这些"用代码而非提示词保证质量"的设施是真实存在且可用的，README 中"Mechanism Layer"一节的自我描述与实际代码相符。测试基线（941 + 213）在同类规模项目中属于上游水平。

但代码库已越过"单人可完整把握"的临界点，出现了三类系统性退化：

1. **抽象层开始空转** —— `ExecProvider` 协议只有本地一个实现、`feature_flag` 生产零调用、`tools/registry.py` 的 schema 与 `file_ops.py` 的实现分居两文件需手工同步。这些是"为了将来扩展"提前建的缝，但扩展从未到来，反而变成维护负担。
2. **同类逻辑多份并行且已漂移** —— 错误标记表两份（内容不同）、`AgentResult` 两个（字段不同）、`.env` 加载两套（`override` 语义相反）、模型表两张（匹配语义相反）、`_push_approval` 三份实现。这是当前最大的可维护性负债。
3. **围栏强度与承诺不符** —— 项目对外承诺 `deny_dangerous` 默认拦截 + 工作区围栏，但围栏只覆盖 `file_ops*`，不覆盖 `bash`/`run_python`/MCP 扩展；黑名单正则锚定过严可逐条绕过。

**最需要立刻处理的不是安全问题，而是三个确定会发生的资源泄漏**（下节严重项 S1–S3）：它们不需要特殊条件，只要正常使用就会触发。

---

## 1. 严重（确定会发生：崩溃 / 数据丢失 / 无界泄漏 / 安全承诺失效）

### S1 · `get_schemas()` 永久污染全局 `TOOL_DEFINITIONS`，工具表无界膨胀
`research_assistant/tools/registry.py:518-529`

```python
if self.allowed_tools is None:
    base = TOOL_DEFINITIONS          # ← 无拷贝，取的是同一 list 对象
else:
    base = [s for s in TOOL_DEFINITIONS if ...]
for ext in self.extensions.values():
    base.append(ext.to_definition()) # ← 向全局 list 追加
```

- **影响**：注册 1 个扩展后连调两次 `get_schemas()`，全局表 14 → 16；此后**新建的、从未注册任何扩展的** `ToolRegistry` 也会看到 16 个 schema（含 2 份重复的 `save_memory`）。`agent.py:634` 每次 `run_agent` 都调一次，长会话下工具表单调增长，重复 schema 每回合重复发给模型 → token 成本持续上升且不可收敛。MCP 扩展会跨 registry 泄漏到不相关的子代理。
- **验证**：`grep -n TOOL_DEFINITIONS` 显示第 23 行定义、521/523 行只读引用，全项目无任何拷贝点。
- **修复**：`base = list(TOOL_DEFINITIONS)` 或 `base = [dict(s) for s in ...]`。

### S2 · `sink_fn` 从未赋值，`_SINKS` 注销分支恒不执行
`research_assistant/web/chat.py:1699`（声明）→ `:2548`（唯一读取点）

```python
sink_fn: Any = None          # 1699 行声明，注释称"本连接在 _SINKS 里的登记凭证"
...
if sink_fn is not None and _SINKS.get(sid) is sink_fn:   # 2548 行 finally 分支
```

- **影响**：`finally` 的注销分支永远为假，`_SINKS[sid]` 永不移除。进程生命期内按会话数无界增长；断连后条目仍指向死信箱，回合帧持续投递进永不被消费的 `asyncio.Queue`（满后丢帧），只有同名会话重连覆盖才被动回收。注释（1698 行）与代码矛盾。
- **验证**：`grep -rn sink_fn research_assistant/` 仅返回 1699（声明）与 2548（读取）两处，**无任何赋值点**。

### S3 · steer 发送失败后 `phase` 永不复位 —— "永远思考中"的残留路径
`frontend/src/stores/chatStore.ts:369-379` 与 `:656-659`

`nudgeReconnectAfterSteerFailure()` 只冲刷缓冲 + 起重连机器，重连 6 次放弃后（`giveUpReconnect()` → `conn="closed"`）**`phase` 仍为 `running`**：状态点永久脉冲、「停止」按钮常驻、`silentSeconds`（ChatView.tsx:159）无限累加、等待横幅永久挂屏。

- **影响**：这是项目历史上反复修过的 bug 类别（R9/R10/R13-B 都在打它），空闲发送路径已由 `applySendFailure`（chatStore.ts:364-367）修好，**steer 路径漏了**。复现：断网后发引导指令 → UI 无终态 → 用户只能重启应用。
- **修复**：`giveUpReconnect()` 中同步 `set({ phase: "idle" })`。

### S4 · 项目导入端点无解压总量上限（zip bomb）
`research_assistant/web/routes.py:309-365`

仅校验**压缩包原始体积** ≤1GB（317 行），随后 `archive.read(info)` 逐条解压写盘（361 行）无任何解压后体积检查。1MB 的 zip bomb 可打满磁盘。端点无认证、无限流。

### S5 · 危险命令黑名单锚定过严，可逐条绕过
`research_assistant/tools/permissions.py:22-43`

逐条实测（正则于 45-47 行以 `IGNORECASE` 编译）：

| 命令 | 规则 | 结果 |
|---|---|---|
| `rm -rf /home/alice`、`rm -rf /opt`、`rm -rf /srv` | 25 行只列 `~`/`$HOME`/`/etc`/`/usr`/`/bin`/`/var` | **放行** |
| `del /s /q C:\Users\Alice` | 33 行 `[a-zA-Z]:\\\s*$` 要求盘符后即结尾 | **放行** |
| `rd /s /q C:\Users\Alice` | 34 行同上 | **放行** |
| `Remove-Item -Recurse -Force C:\Users\Alice` | 38 行同上 | **放行** |
| `vssadmin delete shadows` / `bcdedit /set … recoveryenabled no` / `takeown /f C:\Windows /r` / `icacls C:\ /grant Everyone:F /t` / `robocopy /MIR /PURGE` | 无任何规则 | **放行** |

- **影响**：README 与 `RA_PERMISSION_MODE` 默认值的"deny_dangerous"承诺，与实际覆盖面严重不符。这是本地应用且模型可自由调用 `bash`，攻击面是"模型生成的命令"，该黑名单是**唯一**的缓解措施。
- 附带：49 行 `_EXEC_TOOLS = {"bash","run_python"}`，而 `_execute_extension`（registry.py:563-572）与 `_execute_apply_patch`（617-639）**根本不经过** `PRE_TOOL_USE` 钩子 → 接入 MCP 服务器后，任意远端工具调用不受任何权限拦截。

### S6 · 围栏只保护 `file_ops*`，不保护执行工具
`research_assistant/tools/bash.py:274-281` / `tools/frozen_exec.py:45-52`

`core.safe_resolve`（core.py:17-30）实现是**正确的**（双侧 resolve + `os.sep` 前缀比较，符号链接与 `..` 均拦），`file_ops` 的 5 个调用点也一致。但：

- `run_bash` 对命令内容**零校验**，只校验 `cwd`（registry.py:603）——模型一条 `cmd /c echo x > C:\...` 即绕过围栏；
- `write_anchor` 归巢（registry.py:465-467 注释称"sandbox 恒为 work_dir"）对 bash 完全无效；
- `frozen_exec.run_script` 只做 `p.is_file()`，`expanduser()` 后允许任意绝对路径/UNC。

这是设计取舍（研究助手确实需要跑脚本），但**围栏保护 file_ops、不保护执行工具**这一不对称性应显式记录，不应在注释里声称"沙箱"。

### S7 · MCP 子进程继承完整父进程环境（含 `LLM_API_KEY`）
`research_assistant/mcp_client.py:344` + `:82-89`

`McpServerConnection(...)` 不传 `env`（54/61 行 `self.env=None`），`create_subprocess_exec(..., env=self.env)` 传 `None` → 子进程继承全量环境。**执行工具刚做了 `sanitized_exec_env`（exec_provider.py:44）的净化，在 MCP 侧被整体绕过。** 同时 `parse_servers_config` 接受的 `env` 字段（397-403 行）从不被消费，配置项静默失效。

### S8 · `except BaseException` 吞掉取消信号
`research_assistant/llm/fallback.py:83`

捕获 `asyncio.CancelledError` 后不重抛，只在 `index == len-1` 时 break（85-86 行）。用户点"停止"时取消语义失效，agent 继续向备选模型发完整请求并计费。

同一文件的 17-19 行 docstring 承诺"流式调用只在**尚未发出任何增量**时才允许降级"，但 `chat()` 中没有任何 published-chunk 追踪（正确实现见 `agent.py:1043-1049` 的 `_tracked_chunk`）。`openai_compat.py:228-244` 的 `_chat_streaming` 同类。→ 已向 UI 吐出半截正文后失败会换模型重生成，用户看到两段重复正文。

### S9 · 本地 API 无认证：工作区根可被任意本地进程改写
`research_assistant/web/workspace.py:220-299`

`POST /api/workspace/root` 接受任意绝对路径（233-241 行只校验 absolute + is_dir），切换后 `safe_resolve` 围栏的"根"本身即由请求方指定。配合 `GET /api/workspace/file` 可读取新根下任意文本文件，而 `_PROTECTED_PREFIXES`（145 行）只有 `.env`/`.ra`/`.git` —— `.ssh/id_rsa`、`.aws/credentials`、`.npmrc`、`.netrc` 全部可读。

叠加 `POST /api/workspace/open`（389-417 行）的 `os.startfile()`，且 `desktop.py` 默认 `setdefault("RA_ALLOW_SHELL_OPEN","1")` → 先把根切到 `C:\` 再 open 任意 `.exe` 即执行该程序。

**威胁模型的诚实说明**：`OriginGuardMiddleware`（app.py:96-133）是纯 ASGI 实现且能拦截 websocket scope（这是 `BaseHTTPMiddleware` 做不到的），浏览器跨站攻击基本被挡住（无 Origin 放行、有 Origin 校验回环+端口）。**残余风险不是浏览器，而是同机任意进程/脚本**——它们不带 Origin 即可调用。考虑到 Windows 上同用户态的恶意进程本就能直接读用户文件，实际边际风险有限，因此这是**纵深防御缺口而非危急漏洞**。建议补一次性启动 token（见 §4 P2-3）。

### S10 · 前端：task 通道无重连机制
`frontend/src/stores/taskStore.ts:98-124`

chatStore 有完整的 `scheduleReconnect` 指数退避，taskStore **完全没有**：`onStatus` 只处理 `open`/`error`，断开后 `conn="closed"` 被忽略，TasksView 也不渲染任何断连横幅（对比 ChatView.tsx:308-316 有横幅 + 手动重连）。→ 任务运行中网络抖动 → 活动流静默冻结，用户以为任务卡死。

---

## 2. 中等（明确的坏味道，特定条件下出问题或明显阻碍维护）

### 代码结构

| 位置 | 问题 | 影响 |
|---|---|---|
| `runtime/platform_store.py:51-459` | `_initialize` 单函数 **409 行**，一条 `executescript` 塞 25 张表 DDL + 4 段 ALTER | 全库最难维护单元，建议按域拆 `store_tasks/store_research/store_queue` |
| `runtime/platform_store.py` 整体 2356 行 | 职责横跨任务/事件/队列/科研对象图 | 同上 |
| `tools/registry.py:458` `ToolRegistry` 297 行 | 同时承担 7 项职责：schema 管理、扩展注册、权限/围栏注入、路径预解析、执行快照、产物版本记录、产物索引推送 | 上帝类 |
| `docgen.py:333` `PaperBuilder` 375 行 | 同时管排版模板、标题块、图/表、引用、交叉引用解析 | 上帝类 |
| `views/ChatView.tsx:52-701` | 701 行、15 个 useState/useRef、20+ effect；同时负责深链、滚动锚点、等待看门狗、dock 刷新、分屏、检查器、工作目录 | 前端最大单体组件 |
| `components/chat/SessionList.tsx:33-772` | 772 行，搜索/重命名/归档/置顶/删除/迁移 6 组逻辑 + `SessionItem`（552-772，14 props） | 同上 |
| `__init__.py:23` | 包级顶层 `from .api import generate_paper` | `import research_assistant` 即拉起 httpx + agent + 全部工具链 |
| `research_os.py:54-57` | 注释明确承认"模块级导入会形成循环"，靠函数级延迟导入绕开 | 循环依赖被掩盖而非消除：`runtime/__init__` → `scheduler_dispatcher` → `api` → `agent` → `tools/registry` → `tools/research_os` → 回 `runtime.platform_store` |
| `pipeline/runner.py:180/538/581` | 循环内 `from ..api import ...` 延迟导入散落三处 | 同上 |

### 可维护性 —— 同类逻辑多份并行且已漂移（最大可维护性负债）

| 重复物 | 位置 A | 位置 B | 漂移情况 |
|---|---|---|---|
| 错误标记表 | ~~`retry.py:144-160` `_CONTEXT_LIMIT_MESSAGES`(6 条)~~ **已收敛（2026-08-31）**：retry.py 删私有表，改引用 `llm/errors.py` 导出的公开常量 `CONTEXT_MARKERS`/`MODEL_MARKERS` | `llm/errors.py` `CONTEXT_MARKERS`(9 条) | ✅ 已消除 |
| 模型错误标记 | 同上收敛 | `llm/errors.py` `MODEL_MARKERS`(5 条) | ✅ 已消除 |
| → 后果：同一条 400 报文，经 `classify_response` 判为 ContextLimitError，经 `_is_context_limit`（裸异常路径）判为非超限，**是否重试、UI 提示取决于 provider 走了哪条路** | | | |
| `AgentResult` | `agent.py:52-64` | `orchestrator.py:68-77` | **字段完全不同**，`pipeline/runner.py:25` 不得不用 `as LoopResult` 别名规避 |
| `.env` 加载 | `core.py:60-70` `ensure_dotenv_loaded`（模块级 `_dotenv_loaded` 布尔短路，`override` 默认 False） | `config.py:90-107` `load_project_env`（`override=True`） | **语义相反**；后者被 `api.py:115` 每次生成任务调用 → Web 多工作区并发下构成跨请求配置竞态 |
| 模型表 | `kernel/context.py:42-53` `window_for`（**first-match**，35-41 行注释明确） | `kernel/budget.py:42-57` `price_for`（**longest-prefix**，31 行注释明确） | `gpt-4.1` 在窗口表有 1M（context.py:55）但价格表无条目 → **成本恒为 0**，`BudgetGuard.cost_cap_enforceable` 退化为 false |
| `_push_approval` | `ws.py:204` | `scheduler_dispatcher.py:143` / `chat.py:1976` | 三份实现 |
| `_allocate_output_dir` | `ws.py:54` | `scheduler_dispatcher.py:26` | 逐字重复 |
| `_load_run_state` | `chat.py:333` | `routes.py:1632` | 重复定义 |
| 文件大小格式化 | `MessageBubbles.tsx:35-39` → `"1.0KB"` | `PapersView.tsx:108-113` → `"1.0 KB"` | 输出不一致 |
| 秒/毫秒阈值 | `format.ts:9` 用 `1e11` | `sessionGroups.ts:22` 用 `1e12` | 判定不一致 |
| 运行态文案 | `protocolTask.ts:245` | `SchedulerView.tsx:8` / `ProjectHomeView.tsx:24` / `PapersView.tsx:9` | 四份并行 |
| 连续 user 消息合并 | `llm/anthropic.py:225-243` | `llm/openai_compat.py:128-141` | 逐行同构 |

**注释与代码矛盾（5 处，均已核实）**：
- `utils.py:237-249` `extract_citation_style` docstring 说"Try to extract citation style from BibTeX file or paper metadata"，函数体无条件 `return "BibTeX"` → `api.py:415` 得到的 `citation_style` 恒为常量，**前端展示的"引用风格"是假数据**；
- `orchestrator.py:469` `output_dir / "drafts" / "v1_draft.tex"` 是无副作用的裸表达式语句，注释却称 "kept for legacy .tex input detection"；
- ~~`models.py:30-35` `ProgressUpdate.to_dict`~~ **修订批次复核更正：非矛盾**（`asdict` 确实保留 `details: None` 键，注释成立；初版判为矛盾系误判）；
- `chat.py:1698` 注释称 `sink_fn` 是"登记凭证"，实际从未赋值（见 S2）；
- `MessageBubbles.tsx:11-16` 声称"重新生成…保守语义，不删历史""原气泡文本不回改"，但 chatStore 已改为真替换（`chatStore.ts:491` `truncateHistory`、`:526` `api.patch`）；`messageOps.ts:1-18` 头注同样过期。

**魔法数字**：`agent.py:146`（Jaccard 0.6）、`agent.py:454`（5）、`api.py:366`（mtime 容差 5）、`retry.py`（jitter `0.75+random()*0.5`）、`llm/errors.py:163/173`（`min(...,300.0)` 重复两次）、`bash.py:32`（`_PREFIX_MAX_DEPTH=4`）、`context/sources.py`（`MAX_VECTOR_CANDIDATES=8000`）。

**前端魔法字符串**：localStorage key 硬编码散落 **11 处**无注册表（`artifacts.ts:64`、`sessionStore.ts:17`、`taskStore.ts:64-65`、`prefsStore.ts:16`、`useTheme.ts:5`、`useFirstRunWizard.ts:10`、`sessionArchive.ts:11`、`SessionList.tsx:102`、`ProjectHomeView.tsx:53/57`、`PeerSessionPanel.tsx:15-16`）。

**store 职责重叠**：`uiStore.inspectorOpen`（uiStore.ts:42）与 `TasksView` 本地 `dockCollapsed`（TasksView.tsx:275）**写同一个 localStorage 键** `ra.artifacts.dock.collapsed`，但两处各读各的 → 任务页折叠后会话页不同步。

### 错误处理

**20+ 处静默吞异常**，多数无 `# noqa` 说明、无 `raise ... from e`，traceback 与原始类型全丢：
`bash.py:141-142` / `python_exec.py:70-71` / `frozen_exec.py:117-118` / `core.py:70,142,149` / `utils.py:233,282,310,333,359` / `retry.py:165` / `agent.py:511-512,819-820` / `registry.py:513-516,709-710,745-746` / `mcp_client.py:180,204,265,273-275,283-285,296-298` / `config.py:172-173` / `web/chat.py:2101-2102,2152-2155` / `web/ws.py:334` / `session/store.py:132-133` / `ResearchView.tsx:34` / `AnalysisRunsView.tsx:16-18` / `ArtifactReviewView.tsx:16-18`。

其他明确问题：
- `api.py:356-357` `finally: await llm_client.close()` —— 异步生成器被 GC 时在 `GeneratorExit` 传播路径上 await，触发 "async generator ignored GeneratorExit" 并泄漏 httpx 连接池；
- `api.py:366-371` 对同一目录调用两次 `d.stat().st_mtime`，且 `except Exception: return None` 把权限/IO 错误伪装成"Output directory not found"；
- `agent.py:1005-1006` `is_error` 判定只认 `("Error:", "[DENIED by policy]", "[DENIED by approval]")`，而 `registry.py:572/615/638/717` 实际返回 `"Error executing ..."` → **工具失败在 Anthropic 侧不标 `is_error`，模型把报错当正常结果继续推理**；
- `ProjectHomeView.tsx:71` 切换工作区 `await api.post(...)` 后直接 `window.location.reload()`，**无 try/catch** → 路径非法时静默失败且无任何提示；
- `chatStore.ts:588-607` `openSession` 首个 `await api.get(...)` 在 store 内部无 try/catch，三个调用点都必须自己 `.catch()`，漏一个即未捕获 rejection；
- `SessionList.tsx:113-122` 归档迁移用 `allSettled`（**永不 reject**）后无条件 `localStorage.removeItem` → 全部 POST 失败时本地归档记录仍被清除且无法重放；
- `SessionList.tsx:277` `void postFlags(...)` 不 await 就 `setPendingArchive` → 失败时用户看到"已归档"撤销条但实际未归档；
- `SettingsView.tsx:262` `setCfg({ ...(cfg || {} as ExtendedSettings), configured: true })` → 保存失败路径下把已加载配置清空成 `{}`；
- `App.tsx:104-124` 路由表无 `path="*"` 兜底 → 未知 hash 渲染空白内容区且无逃生提示；
- `chat.py:2106-2117` `_wait_plan_decision` 异常路径泄漏 future：`asyncio.wait` 自身抛出时 `for t in pending_set: t.cancel()` 不执行，两个 future 永久挂起；
- `desktop.py:390-403` uvicorn 在 daemon 线程运行，线程内异常无回传，只检查 `thread.is_alive()`。

### 性能

- **`task_hub.py:144-157 + 238-255` 每个事件帧触发 4 次独立 SQLite 连接**（`get_task`/`list_steps`/`update_step`/`append_event`），而 `platform_store.py:34-49` 的 `_connect` 每次都 `connect` + 3 条 PRAGMA + 建/关。流式文本帧密集时产生数万次建连，同时长期持有 `_lock`（platform_store.py:31）阻塞 UI 侧所有查询。**这是后端最大的性能放大器。**
- `platform_store.py:34-49` 无连接池；
- `platform_store.py:1501-1524 / 534-540` 逐文件/逐节点建连的 N+1；
- **DB 只增不删**：`task_events`/`job_queue`/`notifications`/`artifacts` 无清理路径，Janitor 只处理文件系统（`janitor.py:343-369` 七层全是目录/文件操作）→ 长期工作区数据库单调膨胀；
- `chat.py:449/458` `list_sessions` **在事件循环内**同步遍历全部会话目录并逐个读 `run.json` + `history.json`，未 `to_thread`（`routes.py:844` 的同款快照就正确用了，口径不一致）→ 会话上百时冻结事件循环，同时挂起所有 `/ws/chat` 与 `/ws/generate` 流；
- `chat.py:1386/1298` 图片同步读盘 + base64（单条最多 5×5MB），且每回合对**全部历史条目**重算一次，随历史线性增长；
- `routes.py:269-289 / 1860-1873` 导出包整体构造在内存（`io.BytesIO`）且无大小预检 → 大工作区 OOM；
- `agent.py:74-87 + 716` 每回合全量 `json.dumps` 只为估算 token，长会话下每回合多一次 MB 级序列化，随会话长度线性增长（客户端随后再序列化一次）；
- `registry.py:399-455 + 607-609/628-630/734-736` 每次 `bash`/`run_python`/`apply_patch` 都做**两次全目录 rglob 快照**，最多读入 512 文件 / 32MB；
- `file_ops.py:386, 460-462` `sorted(base.rglob("*"))` 先物化全部匹配再切片 → `**/*` 在含 `node_modules` 的工作区一次性构造数十万 Path，OOM 风险；
- `core.py:86-150` `sync_tree` 每次生成任务都对整棵 `.claude/` rglob + 逐文件 sha256，无缓存/版本短路；
- `citation_verify.py:504-507` 同步 mkdir + 写文件在 async 上下文（同模块其它 IO 都做了 `to_thread`）；`registry.py:695/704` `read_bytes()` 同步读（可能是大文件）；
- `scheduler.py:107-114` 每 2s 轮询无条件执行 3 个写事务，空闲时也持续写 WAL 并抢 `_lock`；
- **同步阻塞进事件循环的其它点**：`api.py:363`（iterdir+stat）、`api.py:127`（全树哈希）、`core.py:475`（`shutil.copy2`）。
- 缓存只增不删：`citation_verify.py:540/564` → `.ra/citation_cache.json` 单调增长。

前端性能：
- `ToolCardView.tsx:183` `diffInputsFor(card).map(...)` 在 render 内同步跑完整 LCS（O(n·m)，上限 2000×2000≈16MB DP 表），**未 useMemo**，每次父组件重渲染都重算 → 展开一张大 `apply_patch` 卡片即主线程长阻塞；
- `ChatView.tsx:53-72` `useChatStore()` 无选择器解构整个 store（zustand v5 无 selector = 订阅全量 state），`SessionDrawer.tsx:17-25` 同样；
- `ChatView.tsx:154-158` 运行中每秒 `setNowTick` 触发整棵常驻 ChatView 重渲染；ChatView 常驻挂载（App.tsx:154），**切到 /settings 后这个 1s 心跳照跑**；
- `SchedulerView.tsx:98` 无条件 3s 轮询 3 个端点，无可见性检测；
- `AgentPanel.tsx:26` 只要 `taskId` 非空就永久 2s/5s 轮询，任务结束后不停；
- `PeerSessionPanel.tsx:103` 分屏打开即 20s 轮询，切页后仍跑；
- `sessionStore.ts:75-84` `setDraft` 每次击键同步 `JSON.stringify` 全量草稿写 localStorage，无防抖；
- 未清理 timer：`ChatView.tsx:691`、`SchedulerView.tsx:71` 裸 `setTimeout`，卸载后仍 setState；
- 大列表无虚拟化：`MessageList.tsx:251`、`TasksView.tsx:505`、`taskPieces.tsx:122`；
- `Composer.tsx:68-72` `EVENT_COMPOSER_SEND` 监听常驻 window + `useHotkeys.ts:90` `allowInInput: true` → **在设置页按 Ctrl+Enter 也会发送会话草稿**；
- `context/sources.py:249-257` 每次检索最多拉 8000 行向量到内存做余弦，无索引过滤。

### 安全性（除 §1 严重项外）

- **已核实安全、未发现问题**：
  - **SQL 注入**：全部参数化；f-string 仅用于 `platform_store.py:1372/1421/1885/1977` 的表名/列名常量白名单；
  - **Markdown XSS**：`Markdown.tsx:13-21` 无 `dangerouslySetInnerHTML`、未引入 `rehype-raw`，ReactMarkdown 会转义原始 HTML；
  - **pickle 反序列化**：全仓无 `pickle` 引用；
  - **CORS**：未使用 `CORSMiddleware`，同源由自研纯 ASGI 中间件把关且能拦截 websocket scope；
  - **密钥回显**：`settings.py:145-151` 掩码正确、`routes.py:152-158` 只回 hostname，未发现日志/错误帧泄漏 API Key 的路径。
- `launcher.py:38` 配置损坏静默 `except Exception: pass`；`save_config` 以默认权限把 `LLM_API_KEY`/`IMAGE_API_KEY`/`PARALLEL_API_KEY` **明文**写入 `%APPDATA%\ResearchAssistant\config.json`（`desktop.py:240-277` 迁移又写进 `.env`，同样明文）；
- `bash.py:77-120` 冻结态 python 拦截前缀白名单过窄：只剥离首 token ∈ `{call,start,cmd,cmd.exe}`（103 行）→ `wsl python a.py`、`pwsh -Command python a.py`、`bash -c python a.py`、`conhost python a.py`、`runas /user:x python a.py` 全部返回 False。`_tokens:45-62` 只识别双引号 → 单引号包裹的 `'C:\Program Files\Python311\python.exe' a.py` 在空格处断成 `Files\python.exe'`，basename 失配放行。88-89 行注释只承认 `%VAR%` 一个盲区，实际盲区远多于此；
- `file_ops.py:185-243` `edit_file` **未调用** `_reject_windows_hazard`，而 `write_file:151` 与 `apply_patch:319` 都调用了 → Windows 保留设备名/NTFS ADS 校验在 edit 通道缺失；`web/chat.py:1484` 直接 import 这个私有函数另做一套，说明该逻辑本应收敛却散在三处；
- `FilePreview.tsx:81` PDF 用同源 `<iframe src="/api/workspace/file?...">` 内联，同源 iframe 会执行 PDF 内 JS，建议加 `sandbox` 或确认后端返回严格 MIME + `Content-Disposition`；
- `artifacts/versioning.py:96-100 / 243-254` `_snapshot` 存在 exists→read 的 TOCTOU；`record_tree` 对每个文件算两次 sha256（247 比较、254 写回）；
- `SourcesView.tsx:46` 绕过 `api.ts` 用裸 `fetch`，无 AbortController 超时（对比 `api.upload` 有 120s），大 PDF 上传挂死时无中断手段。

### 冗余代码

**生产零引用（已 grep 验证）**：
- `config.py:184-194` `feature_flag` —— 仅 `tests/test_r17_platform.py` 使用，而 docstring（188-189 行）要求"所有破坏性/行为变化型重构都必须挂 flag" → 空转的抽象层；
- `constants.py:24` `DEFAULT_MAX_TURNS`、`:26` `DEFAULT_TEMPERATURE` —— 定义后零引用，而 `agent.py:94/97` 与 `288/291` 把 `200`、`0.5` 各硬编码两遍；
- `mcp_client.py:407-416` `connect_mcp_servers_sync`、`get_env_servers` —— 含测试在内全项目零引用；
- `tools/exec_provider.py:65-95` `ExecProvider` Protocol + `LocalExecProvider` —— 纯转发层（82-84、90-95 行各两行转发），除本地实现外无任何实现，registry.py:489 是唯一使用点；
- `llm/errors.py:45-48` `NetworkError` —— 定义后无 raise 点，`classify_response` 从不返回它（测试里手工 raise）；
- `docgen.py:311` `format_apa = format_numbered` —— 遗留别名，仅 tests 使用；
- `runtime/task_hub.py:16` `PAPER_WORKFLOW` —— 无人使用，却把 `workflows.registry` 拉进 `task_hub` 的导入期依赖；
- `runtime/scheduler.py:151-159` `tick()` —— 无调用点；
- `artifacts/versioning.py:140` `snapshot_restorable()` —— 无调用点（UI 侧未接）；
- `session/store.py:117/120` `stage_status`/`done_stages` —— 仅测试引用；
- `core.py:415` `get_source_extensions()` 调用后丢弃返回值 —— 死调用；
- 前端：`chatStore.ts:662 activeChatQuery`、`navModel.ts:59 isChatEntry`、`workspaceSearchModel.ts:16/77/86`（`SEARCH_KIND_LABELS`/`moveHighlight`/`pickEnterIndex`，而 `CommandPalette.tsx:132-145` 用内联代码重写了一遍未复用）、`sessionArchive.ts:46/60/65`（R17 迁服务端后废弃）、`protocolTask.ts:256/264`、`approvalSignal.ts:79/83`、`types.ts:171 TaskState.tlNote`（死字段）；
- `orchestrator.py:94` 每个子代理 `create_llm_client` 新建 `httpx.AsyncClient`，最多 10 个连接池无复用；
- `views/ArtifactReviewView.tsx:17-20` 与 `AnalysisRunsView.tsx:13-20` 被压成 3 行超长 JSX（单行 >4000 字符），`decide`/`rerun`/`attachEvidence` 全部无错误处理，属可读性死区。

---

## 3. 与 Codex / Workbuddy 等同类产品的交互与功能差距

> 说明：本节对比的是**交互范式与能力覆盖**，不涉版本号细节。

| 维度 | 本项目 v3.6.0 | Codex（CLI/IDE/Cloud） | Workbuddy | Claude Code / Cursor |
|---|---|---|---|---|
| **权限呈现** | 全局 `.env` 两个下拉（`RA_APPROVAL_MODE` / `RA_PERMISSION_MODE`）藏在设置页，改完全局生效 | 三档显式切换（Read Only / Auto / Full Access），**会话内随时切** | **右侧权限选择，会话内即时切** | `/permissions`、plan mode |
| **沙箱强度** | 进程内 `exec` + 正则黑名单（可绕过，见 S5） | **OS 级**（seatbelt / Landlock / seccomp）+ **网络默认关闭** | 工作区围栏 | 工作目录围栏 + 命令白名单 |
| **提示词辅助** | 6 条 slash 命令（`budget/model/role/skill/plan/help`，均为控制类）+ 项目长期指令 | `AGENTS.md` + `/mention` 文件引用 | **增强提示词按钮（LLM 扩写）** + 专家/连接器生态 | `/` 命令、`@` 提及、`.cursorrules` |
| **工作区绑定** | **全局单实例**（`os.chdir`），切换需 `location.reload()` | 每任务绑定仓库 | 会话/任务级目录选择 | 打开文件夹即工作区 |
| **可观测性** | ✅ **强**：阶段时间线、实时预算表、events.jsonl 审计、DAG 关键路径指标、产物版本 diff | 中：diff + 命令日志 | 中：工具卡 + 活动流 | 中 |
| **耐久/恢复** | ✅ **强**：SQLite WAL、断线事件回放、孤儿看门狗、精确续跑、项目隔离 | 中 | 中 | 中 |
| **质量门禁** | ✅ CitationGate / DocGate / 复现门禁，失败阻断 final | 无 | 无 | 无 |
| **生态扩展** | MCP 客户端（但子进程继承密钥，见 S7） | MCP | Connector + Expert 市场 | MCP |

### 三项真实差距

1. **权限是"全局配置"而非"会话内控件"** —— 竞品把权限做成输入框旁边的一等公民控件，本项目要进设置页改全局 `.env` 且改完全局生效。用户在会话中途想收紧权限时**没有办法**，只能切页。这是范式差距，不是功能缺失。
2. **沙箱靠正则，竞品靠内核** —— 本项目 `deny_dangerous` 的覆盖面经实测可被常见变体绕过（S5），而 Codex 用 seatbelt/Landlock + 网络隔离。差距是**机制级**的：正则黑名单永远追不完 shell 语法，OS 沙箱是默认拒绝。
3. **提示词增强完全缺位** —— 项目有很强的"执行可观测性"（时间线/预算/审计/diff），但**输入端没有辅助**：无模板库、无变量占位符、无 LLM 扩写。`MessageList.tsx:9-13` 的 `SUGGESTIONS` 是三条**硬编码在组件里**的中文提问，不可配置。这与项目"科研助手"的定位有落差——科研写作恰恰是最需要结构化提示词的场景。

### 本项目的真实优势（应在宣传中强化而非对齐竞品）

- **耐久性与恢复**是竞品普遍没有的：断线只减观察者、孤儿看门狗协作停止后硬取消兜底、环形缓冲 + 会话内单调 seq 的精确续播、被打断回答带 `partial:true` 不丢字。
- **质量门禁前置**（CitationGate/DocGate）把"引用真实性"做成了代码保证而非提示词乞求。
- **产物版本化 + 一键恢复**：Agent/脚本/Python 的间接写入都有版本 diff——这是把"AI 改了我的文件"从恐惧变成可审计操作，竞品普遍只做 diff 展示不做恢复。

---

## 4. 按优先级排序的改进建议

### P0 — 确定会发生的资源泄漏与功能失效（建议本迭代修复）

| # | 动作 | 位置 | 成本 | 收益 |
|---|---|---|---|---|
| P0-1 | `base = list(TOOL_DEFINITIONS)` | `tools/registry.py:518-529` | 1 行 | 消除跨 registry 工具泄漏与 token 成本无界增长（S1） |
| P0-2 | 补 `sink_fn` 赋值，或改为 `pop(sid, None)` 无条件注销 | `web/chat.py:1699/2548` | 5 行 | 消除 `_SINKS` 无界增长（S2） |
| P0-3 | `giveUpReconnect()` 中同步 `phase: "idle"` | `stores/chatStore.ts:656-659` | 1 行 | 堵死"永远思考中"最后一条路径（S3） |
| P0-4 | `except BaseException` → `except Exception` + 显式重抛 `CancelledError` | `llm/fallback.py:83` | 3 行 | 恢复取消语义与计费正确性（S8） |
| P0-5 | 流式降级加 published-chunk 追踪，已吐内容则不换模型 | `llm/fallback.py:50-93`、`openai_compat.py:228-244` | 15 行 | 消除重复正文（S8） |
| P0-6 | 解压前累计检查 `info.file_size`，超限中止 | `web/routes.py:309-365` | 10 行 | 阻断 zip bomb（S4） |

### P1 — 安全承诺与实现对齐（建议下迭代）

| # | 动作 | 位置 |
|---|---|---|
| P1-1 | 重写权限正则：把 `[a-zA-Z]:\\\s*$` 改为 `[a-zA-Z]:\\?` 不锚尾；补 `vssadmin`/`bcdedit`/`takeown`/`icacls`/`robocopy /MIR`；`rm -rf` 覆盖 `/home`、`/opt`、`/srv`；**同时把 `_EXEC_TOOLS` 扩展为"除只读工具外的全部工具"**，让 extension 与 apply_patch 纳入 PRE_TOOL_USE | `tools/permissions.py:22-49`、`tools/registry.py:555-561` |
| P1-2 | MCP 子进程传 `sanitized_exec_env()`，并消费 `parse_servers_config` 的 `env` 字段 | `mcp_client.py:344/82-89/397-403` |
| P1-3 | 本地 API 增加**一次性启动 token**（`desktop.py` 生成写入内存，前端 `api.ts` 注入 header），替代当前"无 Origin 一律放行" | `web/app.py:96-133`、`lib/api.ts` |
| P1-4 | `edit_file` 补 `_reject_windows_hazard`，并把这个校验从 `web/chat.py:1484` 收敛回单一实现 | `tools/file_ops.py:185-243` |
| P1-5 | 扩展 `_PROTECTED_PREFIXES` 覆盖 `.ssh`/`.aws`/`.npmrc`/`.netrc`/`id_rsa` | `web/workspace.py:145-154` |
| P1-6 | 冻结态 python 拦截改为**后缀/路径匹配**而非首 token 白名单；`_tokens` 支持单引号 | `tools/bash.py:45-120` |
| P1-7 | 在 `core.py` 的围栏文档与 README 中**显式记录**：围栏覆盖 file_ops，不覆盖 bash/run_python | 文档 |

### P2 — 性能与可维护性（建议排期，改动面较大）

| # | 动作 | 位置 | 收益 |
|---|---|---|---|
| P2-1 | `PlatformStore` 引入**线程本地连接池**（`threading.local` + `sqlite3.connect(check_same_thread=False)`），并显式 `PRAGMA busy_timeout=30000` | `platform_store.py:34-49` | 直接消除 S 级别最大的性能放大器：每帧 4 次建连 → 0 |
| P2-2 | 把每帧 4 次调用合并为**单个事务**（一次连接内 `get + update + append`） | `task_hub.py:144-157/238-255` | 配合 P2-1，事件写入开销降一个数量级 |
| P2-3 | `list_sessions` 的目录遍历与 `run.json` 读取下放 `asyncio.to_thread` | `web/chat.py:449/458` | 消除事件循环冻结（对齐 `routes.py:844` 既有口径） |
| P2-4 | 拆分 `PlatformStore`（2356 行、`_initialize` 409 行）为 `store_tasks` / `store_research` / `store_queue` 三模块 + 组合门面 | `runtime/platform_store.py` | 全库最大可维护性负债 |
| P2-5 | 收敛重复实现（见 §2 表格）：错误标记表、`AgentResult`、`.env` 加载、两张模型表、`_push_approval`、`_allocate_output_dir`、`_load_run_state` | 多处 | 消除"改一处漏一处" |
| P2-6 | 给 `task_events`/`job_queue`/`notifications` 加保留期清理（Janitor 扩展到 DB 侧） | `runtime/janitor.py` | 阻止数据库单调膨胀 |
| P2-7 | `ToolCardView` 的 LCS 加 `useMemo`；`ChatView`/`SessionDrawer` 用 zustand selector 订阅 | 前端 | 消除主线程长阻塞与全量重渲染 |
| P2-8 | 抽取 `useNowTicker(500)` 共享（ApprovalCard/PlanCard 各起一个 interval）；给轮询加 `document.visibilityState` 检测 | 前端 | 减少无谓渲染与请求 |
| P2-9 | 建立 localStorage key 注册表，收敛 11 处散落的魔法字符串 | 前端 | 防同名键冲突（现已有 `ra.artifacts.dock.collapsed` 双写冲突） |
| P2-10 | 修正 5 处注释与代码矛盾（见 §2 表格），特别是 `utils.py:237` 的假 `citation_style` | 多处 | 假数据已在前端展示 |

### P3 — 清理（低风险，可随时做）

删除生产零引用的死代码：`config.feature_flag`、`constants.DEFAULT_MAX_TURNS/TEMPERATURE`、`mcp_client.connect_mcp_servers_sync/get_env_servers`、`exec_provider.ExecProvider` 抽象、`llm.errors.NetworkError`、`docgen.format_apa`、`task_hub.PAPER_WORKFLOW`、`scheduler.tick`、`versioning.snapshot_restorable`、`core.py:415` 死调用，以及前端 8 处仅测试引用的导出。

**关于 `launcher.py`（269 行）**：它不是孤儿模块——`build.py:270` 的 `HIDDEN_IMPORTS` 显式列出 `research_assistant.launcher`，`build.py:303` 的 `--restricted` 构建以 `launcher_restricted.py`（转发 `launcher.main()`）为入口。但正式构建（`build.py:308`）走 `launcher_desktop.py`，`pyproject [project.scripts]` 也只暴露 `desktop`。建议：确认不再需要 `--restricted` 试用版后，连 `launcher.py` + `launcher_restricted.py` + `build.py` 的两处引用一并删除；在确认前**保留**。

---

## 5. 审阅方法与局限

- **方法**：四个并行深度审阅通道分别精读（1）后端核心层 28 文件 9719 行（2）平台/Web 层 36 文件（3）前端 79 文件（4）交叉验证；本人对 S1/S2/S5/S9 及 `Composer`/工作区/权限三处关键代码做了**独立复核**，均逐行确认。
- **局限**：
  - 未做动态验证（未运行应用、未跑 fuzz）；S5 的绕过是**正则静态推导**，非实机执行；
  - `bash`/`run_python` 的沙箱逃逸为**设计取舍**（研究助手需要执行能力），本报告只标注不对称性，不主张封死；
  - 前端性能问题多基于代码结构推断，未做 Profiler 实测；
  - 未审计 `.claude/skills/` 下的第三方技能脚本（README 声明其为外部内容，`pyproject` 的 ruff 配置也已 `extend-exclude = [".claude"]`）。
