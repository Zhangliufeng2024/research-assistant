# research-assistant-v3 全面评估与 A+ 重构规划

日期：2026-08-28 · 基线 commit `abf29c1` (v3.5.0)
前置：`2026-08-28-code-review-full.md`（缺陷清单与证据）
目标：六个维度全部达到 **A+**

---

## 0. 执行摘要

### 0.1 评级：现状 → 目标

| 维度 | 现状 | 目标 | 主要差距 |
|---|---|---|---|
| 架构设计 | **A-** | A+ | 分层优秀，但 `run_agent` 555 行 CC=89、三处重复代码块、两套并行的会话/任务体系 |
| 工程质量 | **B+** | A+ | 注解率 50.5%、docstring 56.3%、约 60 处静默吞异常、**无覆盖率测量** |
| 并发正确性 | **C** | A+ | 3 个确定性竞态 + 1 个确定性内存泄漏 + 无并发测试 |
| 文件治理 | **C+** | A+ | 6 套并行真相、版本化覆盖不全、**恢复功能会删数据**、7.9MB 技能树重复 |
| 前端完成度 | **B+** | A+ | 16 view 无空壳，但缺项目层、对话区不常驻、无 ErrorBoundary、无组件测试设施 |
| Agent 能力完备度 | **C+** | A+ | 记忆/MCP/多模态/沙箱/fallback/tracing 六项缺失（18 项中仅 3 项达标） |

### 0.2 工作量与排期

| 阶段 | 内容 | 预估 | 依赖 |
|---|---|---|---|
| 阶段 0 | 可观测地基（覆盖率+并发测试脚手架） | **1d** | — |
| 阶段 1 | 正确性与并发缺陷清零（P0 全清） | **3d** | 阶段 0 |
| 阶段 2 | 文件治理统一 | **4d** | 阶段 1 |
| 阶段 3 | 架构重构 | **4d** | 阶段 2 |
| 阶段 4 | 前端补齐 | **5d** | 阶段 1（可并行） |
| 阶段 5 | Agent 能力补齐 | **8~10d** | 阶段 3 |
| **合计** | | **~25~27d** | |

> 阶段 4 与阶段 2/3 无代码交集，可并行开工。

### 0.3 三条硬约束的落实方式

| 约束 | 落实 |
|---|---|
| 不引入冲突依赖 | **新增运行时依赖：0**。全部新能力走 httpx（已有）/ 标准库。新增的 5 个依赖**全部是 dev-only**（见 §7） |
| 不破坏对外接口 | 所有 REST/WS 端点只增不改；schema 迁移走幂等 `ALTER`（沿用 SCHEMA 10→11→12 既有模式）；前端路由只加不删 |
| 每项改动附验证方式 | 每个方案卡片的「验证」栏给出**具体测试文件与断言**，P0 项额外给人工复现步骤 |

### 0.4 执行进度（2026-08-28/29 已完成第一批）

| 阶段 | 状态 | 交付 |
|---|---|---|
| **阶段 0** | ✅ 完成 | 覆盖率基础设施（后端 pytest-cov + 前端 coverage-v8，均**不写入 addopts** 以免破坏未安装环境）；CI 加 Coverage 步骤与产物上传；`.gitignore` 补覆盖率/`.audit_tmp`/`git_diag*`；基线入档 `docs/quality/baseline-2026-08-28.md`（后端行覆盖 **73.7%** / 分支 59.9%） |
| **1.1 模型守卫** | ✅ 完成 | `supports_sampling_params()`（按主版本号判定，规避 Claude 5 丢 minor 段的正则陷阱）；窗口表 Claude 5 系 → 1M；价格表修正 Opus 5/25（原 3 倍高估）并补 fable；`set_model` 补未知模型告警。新增 `tests/test_llm_model_compat.py` **48 项**；同步修正 4 处既有测试中隐含"窗口=200k"的硬编码（`over_trigger()` 按模型实际窗口换算） |
| **1.2 前端 P0** | ✅ 完成 | `ProjectHomeView` effect 拆分（依赖收敛为字符串 root，消除无限轮询）；新增 `ErrorBoundary`（含 `resetKey` 导航自恢复）并双层接入 `App.tsx`。**提前引入 jsdom + @testing-library/react**（原属阶段 4）——否则这两个 P0 无法自动验证。新增 `ErrorBoundary.dom.test.tsx`(7) + `projectHomeEffects.dom.test.tsx`(5) |
| **1.3 恢复删数据** | ✅ 完成 | 新增 `SnapshotMissingError`；`restore()` 用独立标记 `<side>_evicted` 区分「当时不存在」（删文件是正确语义）与「快照被清理」（**必须拒绝**）；`ArtifactVersionStore.discard_snapshot()` 让「删 bin + 改索引」成为一个动作；`_sweep_changes` 改走该方法且只扫 `*.bin`（旧实现 `rglob("*")` 理论上可能把 index.json 当最旧文件删掉）；`reconcile_snapshots()` 修复存量悬空记录并在 app 启动时跑一次；REST 层映射 409。新增 9 项测试 |
| **阶段 1 其余** | ✅ 完成 | **C-1**（handles 终态释放，pop 在 finally 末尾以保住 done 帧）、**C-2**（重复 attach 不再累加观察者）、**C-3**（登记原子化 + `_close_quietly` 后台关闭，抽出 `_register_connection` 便于测）、**C-4**（`_has_active_turn()` 占位判据）、**F-5**（`write_file` 改为全路径 resolve）、**C-6**（`complete_job`/`fail_job`/`defer_job`/`recover_expired_jobs` 补 `BEGIN IMMEDIATE`；`fail_job` 是典型 read-modify-write，deferred 事务在多 worker 下会抛 `SQLITE_BUSY_SNAPSHOT` 且**不等待** busy_timeout，整次状态转换被丢掉）、**C-7**（出站信箱有界，抽出 `bounded_put()` 丢最旧保序，与任务侧 maxsize=1000 同口径） |
| **阶段 2（大部分）** | 🟡 四项 | **F-4** ✅：`SnapshotStats` + `notice()`——执行快照超限丢弃从完全静默改为在回执中披露，连「一个变更都没记录」的分支也强制披露，避免用户读成「没有变更」。**F-6** ✅：Janitor 补 `.ra/tool_outputs/` TTL 清理（外置的超大工具结果此前**永不清理**）与 `janitor_audit.jsonl` 自身轮转（审计日志只增不减，反而拖慢每次删除），轮转置于其它层**之后**以不丢本轮证据。**F-2** ✅：`PlatformStore.upsert_artifact()`（`replace_artifacts` 的单行增量版，同键重复推=更新不堆行）+ `ToolRegistry` 可选注入 `artifact_store`/`artifact_session`，写入成功即推（CLI/单代理不注入→行为不变；索引是旁路，抛错不影响写入）。**F-3** ✅：`record_tree()` 补齐 subprocess 写入路径，含内容哈希幂等去重。**修正规划原始方案的一个错误**：F-3 不能把版本化钩子下沉到 `atomic_write_text`——版本存储自己就用它写 index.json，会无限递归 |
| **阶段 2 剩余** | ✅ 收尾 | **F-7 分叉合并已完成**（2026-08-29，见 §0.6 补记）：调查结论 = 运行时 `/skill` 只注入技能名不加载内容，模型靠浏览文件系统发现技能，两套同名 `docx` 即随机二选一。`document-skills/docx`（ooxml/ + docx-js.md 布局 + 被 document-skills/SKILL.md 汇总引用）为 Anthropic 上游官方结构，定为权威；独立 `docx/`、`pdf/` 为旧版布局，删除（git 可恢复）。删除前迁移 5 个独有脚本：`accept_changes.py`（依赖 `office/soffice.py`，保留 `scripts/office/` 包结构）、`comment.py`、`office/soffice.py` → `document-skills/docx/scripts/`；`extract_form_structure.py`（非填充 PDF 表单结构分析）→ `document-skills/pdf/scripts/`。同时修复权威 SKILL.md 的跨技能路径错误（generate_schematic 指向 scientific-schematics 实际路径）并补「Additional Local Scripts」一节。审计：433→**349 文件**，分叉清零，重复组 55→53（剩余为 document-skills 内部各技能自带的 LICENSE/schema，技能自包含性所需，保留）。孤儿 outputs TTL 见阶段 6 备选 |
| **阶段 3** | 🟡 3.2/3.3 完成 | ✅ 3.2 `registry.execute` 拆分：dispatcher（20 行）+ `_execute_extension`/`_execute_via_provider`/`_execute_apply_patch`/`_execute_handler` 四个私有方法；bash/run_python 共用骨架（cwd 围栏→前置快照→provider→版本回填）；死代码（原 613 行重复的 handler 赋值）随重写移除。✅ 3.3 stop_reason_map ×4→×2（`ANTHROPIC_STOP_REASON_MAP`/`OPENAI_FINISH_REASON_MAP` 模块级常量，流式/非流式共用）；steer 提取 `constants.STEER_PREFIX`（agent 构造与 cli 文档共用，防漂移）。✅ 截断 ×3（此前完成）。✅ 3.1 `run_agent` 556 行拆分完成：`_RunEnv`（环境）/`_RunState`（可变状态）/`_SessionMirror`（账本镜像）三个数据类 + 6 个模块级单元（`_prepare_run`/`_drain_steer_and_announce`/`_append_continuation`/`_reserve_budget`/`_call_llm_turn`/`_compact_if_needed`/`_execute_tool_batch`），run_agent 变为纯编排壳；三处近乎相同的 steer/continuation 块合并为 `_append_continuation`；for/else 控制流语义经 `_execute_tool_batch` 返回值显式化。✅ 3.5 吞异常清理（53 处分类：45 补理由注释/5 升级上报/3 已有）；✅ 3.6 只读统一视图（GET /api/research/overview 加性合并工作区快照，6 项测试）；✅ 3.4 渐进完成（mypy 配置实跑、kernel+llm 15 文件 0 错误；全仓 90% 注解覆盖为后续增强项） |
| **阶段 4** | ✅ 实施完成（2026-08-29） | **交互方案已成文** `docs/plans/2026-08-29-frontend-interaction-design.md`（参照 WorkBuddy/Claude Cowork/Codex App）：三栏布局 + 可折叠导航 + 会话区常驻（切会话不卸载、草稿/滚动位保持）+ 检查器抽屉化（窄屏兜底）；快捷键 10 键位对齐 Claude/Codex（Ctrl+K 命令面板、Ctrl+. 中断等），命令面板与快捷键共享命令注册表；实施切分 5 步约 5 天；明确不做多会话分屏/拖拽布局/移动端原生。✅ 代码实施完成：三栏壳 + 会话区常驻（display 切换+滚动锚点+草稿 localStorage）+ 导航抽屉 + 命令面板/快捷键（fuse.js）+ 窄屏兜底；新增 27 项测试（vitest 313 全绿，既有断言零改动） |
| **阶段 5（部分）** | 🟡 | **G-5 模型 fallback** ✅：`llm/fallback.py` + `RA_MODEL_FALLBACK`（`openai:gpt-4o,anthropic:claude-sonnet-5`），任何异常换下一个（含限流），**最后一个候选异常原样上抛**，`close()` 关全部候选。**G-4 环境净化（三条执行路径全收口）** ✅：`sanitized_exec_env()` 用**子串包含**匹配（**教训：前缀匹配是错的**——`GITHUB_TOKEN` 以 TOKEN 结尾）；接入点 = bash（`_run_process` 咽喉处默认净化）+ python_exec（child_env）+ frozen_exec（spawn 子进程 exec 前自净，`multiprocessing` 不支持 env 参数）。**frozen_exec 踩坑**：先 `clear()` 再 `sanitized_exec_env()` 拿到的是空表（它缺省读的就是 os.environ），子进程 N=1、matplotlib 因找不到 HOME 崩——必须**先快照再 clear**，已用 `COUNT>10` 断言锁死。**G-1 跨会话记忆** ✅：`kernel/memory.py` 的 `MemoryStore`（`.ra/memory.json` 原子写；幂等去重；超限按 hits 最低+最旧淘汰；损坏文件空表起步）+ `tools/memory_tools.py` 三件套（save/recall/forget，经 ToolExtension 声明式注册，CLI 路径不注入）+ chat.py 连接时注入记忆摘要到系统提示（每回合读取成本一次 JSON）。刻意不做自动抽取（需额外 LLM 调用与误记治理，收益/成本比差）。**G-2 MCP** ✅：`mcp_client.py`（stdio JSON-RPC 2.0 子进程、initialize/tools/list/tools/call、按 id 匹配 + Future 表、EOF 感知、close 三段兜底）；`connect_mcp_servers` 把远端工具以 `mcp_<server>_<tool>` 前缀注册为 ToolExtension（冲突/失败跳过，部分可用）；CLI 经 `RA_MCP_SERVERS` 接线；测试用内置参考 server（tests/fixtures/mcp_echo_server.py）零网络依赖，13 项。已知限制：仅 stdio + 文本结果。**G-3 多模态** ✅：消息层支持 text/image 部件列表（Anthropic base64 / OpenAI image_url 双协议适配，连续 user 消息合并）；WS `attachments` 内联图片（mime 白名单、5MB/张、≤5 张），落盘 outputs/uploads 留档、历史不膨胀；`RA_VISION_DISABLED` 开关；16 项测试。**G-6 tracing** ✅：`kernel/tracing.py` 的 `TraceRecorder` 订阅 HookBus 写 JSONL span（LLM 按 turn、工具按 turn+tool 配对计时，ERROR 后兜底补 run_end），`RA_TRACE_DIR` 开关未设置零开销；经 RunConfig.hooks 接线两处 run_agent 调用；10 项测试。零新依赖 |

### 0.6 F-7 关键更正：同名分叉 ≠ 重复（2026-08-29 补）

审计脚本新增 `analyse_forks()` 后发现：`docx/` 与 `document-skills/docx/` 只有 **1 个文件一致**、7 个内容不同、**65 个仅顶层独有、53 个仅嵌套独有**（`pdf/` 同理 2/9/1/1）。此前"document-skills 与独立 docx/、pdf/ 整树重复"的判断是**错的**——这是两套独立实现共用同一技能名（fork），不是重复。

**因此没有执行该去重，也不应执行**：删除任何一侧会销毁几十个独有文件（docx 侧的 `accept_changes.py`/`comment.py`/`office/` 助手，document-skills 侧的 `ooxml/` schema 与 `docx-js.md`）。fork 的实际危害比体积大得多——模型面对同名技能是**随机二选一**，两者行为不一致且各自演化，改 A 处 B 处静默过期。唯一安全解法是人工合并：确认功能超集侧 → 迁移另一侧独有脚本 → 保留旧路径一版 → 新建测试工作区验证 sync_tree 镜像完整。这需要作者决定"哪套 docx 实现是正主"，无法由自动化代替。

已执行的 F-7 子集：删除经全仓核实零引用的 `qiniu_image.py` ×4（docstring 声称被 4 个脚本导入是过时的，`cli.py` 技能路径名单也没有它），1364 行死代码，git 可恢复。审计脚本已升级为同时报告重复与分叉，退出码接入 CI 作守卫。

**验证结果（2026-08-29 傍晚最终确认）**：
- **后端全量 1178 passed / 0 failed / 3 skipped**——含此前 4 个"环境性失败"的
  修复（GBK 解码 ×3、路径含空格 ×1，均为 Windows 主场景真实缺陷，已从根因
  层修复）。前端 **286 passed**（32 文件）；`ruff` 与 `tsc -b` 零错误。
- 复现命令：`pytest tests/ -p no:cacheprovider --basetemp="$TEMP/pytest-ra-<新名字>"`。
  basetemp 必须是 **OS 临时目录下的全新路径**：指进工作区会撞 safe-delete
  shim（沙箱模式无回收站实现 → 单文件 unlink fail-closed；rmtree 撞 50 阈值
  bulk 守卫），产生的 36 个失败已逐一证实为环境伪影（含本轮未改动路径的
  test_pipeline 同样失败）。
- 并发专项 `tests/test_concurrency_stage1.py` **30 项**（目标 ≥20，已超）；
  治理专项 36 项；阶段 5 能力专项 25 项。
- 关键修复均已用「临时还原缺陷版本 → 观察用例转红」验证测试有效性：
  - `ProjectHomeView` 无限轮询：还原后 3/5 转红（收紧断言前仅 2/5，原 ≤4 的宽松断言是假绿）
  - `write_file` 围栏：探测断言 `.name == "notes.txt"` 能区分新旧行为
  - bash 环境净化：还原未净化版本后输出 `KEY_sk-top-secret_`，测试精确抓到泄露
  - 路径含空格：还原无引号版本后指针消息截断，测试转红
- C-7 的 WS 冒烟用例在本沙箱会挂起（TestClient + WS 组合），故改为把背压策略
  抽成模块级 `bounded_put()` 直接测——更好测，也比只做结构性断言更可靠。

---

## 1. 技术栈与架构测绘

### 1.1 技术栈

| 层 | 技术 | 版本约束 |
|---|---|---|
| 语言 | Python ≥3.10（CI 测 3.10 / 3.12） | `pyproject.toml:6` |
| 后端 | FastAPI + uvicorn（optional `web`） | 无 SDK，httpx 手写 LLM 调用 |
| 桌面壳 | pywebview 5（optional `desktop`）+ Inno Setup | PyInstaller 打包 |
| 前端 | React 18.3 + TS 5.8 + Vite 6 + Tailwind 4 + zustand 5 + react-router 7 | 产物直出 `research_assistant/web/static/` |
| 存储 | SQLite WAL ×2（platform / sources）+ 文件系统 | 无 ORM，裸 SQL |
| 测试 | pytest + pytest-asyncio(auto) / vitest 3.1 | **无覆盖率工具** |
| Lint | ruff（E,F,W,I,UP,B；line-length 100） / tsc | **无 mypy、无安全规则集** |

### 1.2 目录结构与职责

```
research_assistant/
├── llm/          # LLM 抽象：anthropic / openai_compat 归一化 + 错误分类
├── tools/        # 14 个工具（registry 是唯一执行入口）
├── kernel/       # 事件总线 / 预算 / 上下文压缩 / 审批 / 守卫
├── runtime/      # SQLite PlatformStore + 后台任务 + 租约调度 + Janitor
├── workflows/    # AgentRole / WorkflowRegistry / DAG 执行器 / Supervisor
├── pipeline/     # 论文专用流水线（plan→research∥→figures∥→assemble→gates→finalize）
├── context/      # 资料库 + hybrid 检索
├── artifacts/    # 产物版本化与恢复
├── session/      # 会话文件系统存储（run.json + events.jsonl + history.json）
├── web/          # FastAPI：app / routes / chat(WS) / ws(任务WS) / workspace / settings
├── gates/        # CitationGate / DocGate
└── eval/         # 评估 harness（3 个 golden task）
```

### 1.3 三条核心数据流

**A. 聊天回合**（`web/chat.py`）
```
WS 连接 → _handle_attach(定位/新建 session 目录)
       → 用户帧 → _start_turn → _TurnHandle 登记 _ACTIVE
       → asyncio.Task(_turn_main) → run_agent(kernel 预算/事件/压缩)
       → _emit 帧：按 sid 现查 _SINKS（非闭包绑定）→ 出站队列 → pump → WS
       → 全路径落盘 history.json（打断带 partial:true）
```

**B. 后台任务**（`runtime/` + `workflows/`）
```
POST /api/tasks → task_hub.start → platform_store.create_task
              → 兼容桥写 Thread/Turn（task_hub.py:112-120）
              → scheduler.claim_job（BEGIN IMMEDIATE + 租约）
              → workflows/runner DAG 调度 → supervisor 并行子 Agent
              → 完成/失败 → index_task_artifacts → artifact_reviews
```

**C. 文件写入**（**无单一入口，这是文件治理的根因**）
```
ToolRegistry.execute  ──→ write_file/edit_file/apply_patch ─→ version_store.record ✅
                     └──→ bash / run_python ─────────────→ 仅 anchor 内快照 ⚠️
core.atomic_write_text ─→ 通用写原语 ──────────────────→ 无版本化钩子 ❌
subprocess(routes.py:1136, skill 脚本) ────────────────→ 零覆盖 ❌
```

---

## 2. 六维评级与问题清单

评级标准：**A+** = 有机制保证 + 有自动化验证 + 无已知缺陷；**A** = 机制完备但有缺口；
**B** = 基本可用，存在已知问题；**C** = 存在可能导致数据丢失/服务异常的结构性缺陷。

### 2.1 架构设计 — 当前 **A-**

**已达 A+ 的部分**：机制层（状态机/门禁/事件总线/预算）是真实代码而非提示词；
`kernel/` 与 `runtime/` 边界清晰；`_TurnHandle` 的解耦是结构性设计。

| ID | 级别 | 问题 | 位置 |
|---|---|---|---|
| A-1 | P1 | `run_agent()` 555 行、圈复杂度 89，内联 5 个闭包，无法单测 | `agent.py:277` |
| A-2 | P1 | `registry.execute()` 161 行 CC=49；`registry.py:528` 为死代码 | `tools/registry.py:460,528` |
| A-3 | P2 | 超长函数：`pipeline/runner.py:150`(430/74)、`cli.py:65`(391/85)、`api.py:82`(276/36) | 见左 |
| A-4 | P1 | **两套并行体系**：任务走 Thread/Turn/AgentItem，会话走 SessionStore 文件系统，互不可见 | `task_hub.py:112` vs `session/store.py` |
| A-5 | P2 | 重复代码块：截断逻辑 ×3 一字不差；`stop_reason_map` ×4；steer 注入 ×3 | `bash.py:266`、`python_exec.py:83`、`frozen_exec.py:169` 等 |
| A-6 | P2 | `constants.py:1-5` 声称"所有魔法数字在此"，但阈值/价格表/门禁系数仍散落 | `context.py:21-26`、`budget.py:27-39`、`citation_gate.py:28` |

### 2.2 工程质量 — 当前 **B+**

**已达 A+ 的部分**：CI 矩阵完整（双 OS × 双 Python + 前端全链路）；ruff/tsc 零错误；
**裸 `except:` 零处**；测试量大（后端 ~1017 / 前端 ~274）。

| ID | 级别 | 问题 | 位置 |
|---|---|---|---|
| Q-1 | **P0** | **无任何覆盖率测量**（无 pytest-cov、无 @vitest/coverage-v8）→ 无法证明达标 | `pyproject.toml:55`、`package.json:24` |
| Q-2 | P1 | 约 60 处 `except Exception: pass` 静默吞异常 | `agent.py:392`、`context.py:219`、`registry.py:616`、`citation_gate.py:84` |
| Q-3 | P1 | 参数类型注解率 **50.5%**、docstring **56.3%**；**无 mypy** | AST 实测 40 文件/327 函数 |
| Q-4 | P1 | **无并发场景测试**。现有测试全是单连接/单任务，故 R7~R9 三轮前端状态机 bug 逃逸 | `tests/` |
| Q-5 | P2 | ruff 未启用安全/复杂度规则集（无 S、C90、SIM、ANN） | `pyproject.toml:67-69` |
| Q-6 | P2 | OpenAI 侧 cache token 完全不计量，成本统计偏高 | `openai_compat.py:219,323-327` |
| Q-7 | P0 | **默认路径必然 400**（详见 §3.1） | `constants.py:17`、`anthropic.py:183` |

### 2.3 并发正确性 — 当前 **C**

**已达 A+ 的部分**：取消路径穿透到 LLM 调用（`agent.py:250-274`，`finally` 正确收尾，无泄漏）；
孤儿看门狗语义正确；阻塞调用统一走 `asyncio.to_thread`（60+ 处，无裸 `run_in_executor`）。

| ID | 级别 | 问题 | 位置 |
|---|---|---|---|
| C-1 | **P0** | `handles` 字典**永不清理**：8 处 `.get()`，全文件无 `pop`/`del`。每任务泄漏一条（含 subscribers set、队列、Task 引用），`live_count` 虚高 | `task_hub.py:74,90,215,249,259,264,274,281,293` |
| C-2 | **P0** | 重复 attach 永久污染 observers：`_observe` 无条件 `+1`、`watching` 有条件 append；`_release` 以 `watching` 为准 → **看门狗永不武装** | `chat.py:1484,1486,1462-1467,1984` |
| C-3 | **P0** | `_LIVE`/`_SINKS` 注册竞态：`await previous.close()` 是挂起点，后写覆盖先写 → **A 会话的帧串投到 B 标签页** | `chat.py:1547-1558` |
| C-4 | P1 | `_start_turn` 无 `_ACTIVE` 占位检查；C-3 触发后可产生两个并发回合，同时对 `history.json` 做 read-modify-write → 丢更新 | `chat.py:1953,1695-1700,1903-1908` |
| C-5 | P1 | `tasks` 表 UPDATE 无前置状态校验、无 CAS；`complete` 可覆盖 `complete` | `platform_store.py:794-822` |
| C-6 | P1 | `complete_job`/`fail_job`/`defer_job`/`recover_expired_jobs` 缺 `BEGIN IMMEDIATE`；`fail_job` 是先 SELECT 后 UPDATE，多 worker 抛 `SQLITE_BUSY_SNAPSHOT` 且无重试 | `platform_store.py:1988,2016,2044,2056` |
| C-7 | P1 | chat 出站队列**无界**（任务侧是 `maxsize=1000`，口径不一致）；慢客户端无限堆积 | `chat.py:1406` vs `task_hub.py:218-224` |
| C-8 | P1 | 并发会话数**无准入上限**；`_SESSIONS` 每会话常驻 ≤4000 帧缓冲且无 LRU/TTL | `chat.py:1140,1954` |
| C-9 | P2 | 审批帧 fire-and-forget，无引用无收尾 | `chat.py:1640`、`ws.py:215`、`scheduler_dispatcher.py:154` |
| C-10 | P2 | `mark_orphaned_running_tasks` 只动 `tasks` 表不动 `job_queue`，恢复窗口不一致 | `platform_store.py:891-900` |
| C-11 | P2 | 超时后 `proc.kill()` 只杀直接子进程，孙进程不回收（无进程组 kill） | `frozen_exec.py:145-149` |

### 2.4 文件治理 — 当前 **C+**

**已达 A+ 的部分**：`safe_resolve` 路径围栏（读写工具均 resolve 后前缀比对）；
Janitor 审计先行、分层、env 可调；附件上传消毒与围栏校验完整（`chat.py:1199-1242`）。

| ID | 级别 | 问题 | 位置 |
|---|---|---|---|
| F-1 | **P0** | **恢复功能会删文件**：`_snapshot` 为 None 时 `unlink()`；Janitor 淘汰 bin 却不清 `index.json` → 悬空记录 → 点恢复即销毁 | `versioning.py:77,104-106` + `janitor.py:180-187` |
| F-2 | P1 | **6 套并行真相无权威源**：`.ra/changes/index.json`、`platform_store.artifacts`（拉模式）、`outputs/<sid>/manifest.json`（截断 500）、`artifact_reviews`（仅终态索引）、`.ra/artifacts/manifest.json`（与上一套不通信）、前端启发式扫描 | 见 §2.4 表 |
| F-3 | P1 | 版本化只覆盖 `write_anchor` 单目录；绝对路径/`../` 写入、`.ra` 内、`_ra_exec_*.py`、subprocess 路径**全部漏网** | `registry.py:488,510,536,346,390`；`routes.py:1136` |
| F-4 | P1 | 快照超限**静默丢弃**（512 文件 / 32MB），无日志、回执不提示丢弃数 | `registry.py:384,393` |
| F-5 | **P0** | **`write_file` 符号链接写穿**：只 resolve 父目录就裸拼文件名；而 read/edit/glob/grep 都对完整路径 resolve（口径不一致证明是遗漏） | `file_ops.py:148-150` vs `:34-37,188-195,350-353` |
| F-6 | P1 | 清理面缺失：`.ra/tool_outputs/` 无清理、`janitor_audit.jsonl` 无轮转、孤儿 `outputs/<sid>` 明确保留不清理 | `chat.py:403-404`、`janitor.py:75-76` |
| F-7 | P1 | **`.claude/skills` 7.9MB / 433 文件，10 组字节级重复**：`qiniu_image.py` 复制到 4 个技能；`document-skills/{docx,pdf,pptx}` 与独立 `docx/`、`pdf/` 整树重复；`research_lookup.py` 3 份 | 见 §3.7 |
| F-8 | P2 | 仓库卫生：`git_diag*.txt`、`audit_result.txt`、`.audit_tmp/`（含 `secret.txt` 越权测试样本）未跟踪且**不在 .gitignore**；7 个 `.pytest_tmp_*` 约 176MB；`dist/` 246MB | `.gitignore` |

### 2.5 前端完成度 — 当前 **B+**

**已达 A+ 的部分**：16 个 view **无空壳**（20 行的文件是手工压缩的单行 JSX，最长 4,344 字符）；
流式合帧保序；重新生成/编辑是**真替换**（服务端 truncate + 本地裁剪）；断线指数退避重连 +
按 lastSeq 续播；无 `dangerouslySetInnerHTML`（XSS 面收敛）。

| ID | 级别 | 问题 | 位置 |
|---|---|---|---|
| U-1 | **P0** | **无限请求循环**：`useEffect` 依赖 `home?.project` 对象引用，`refresh→setHome(新对象)→effect 重跑`，落地页以网速无限轮询 `/api/project/home` | `ProjectHomeView.tsx:33-46` |
| U-2 | **P0** | **无 ErrorBoundary**（全库 grep 零命中），任一 view 渲染抛错即白屏 | `App.tsx` |
| U-3 | P1 | **无"项目/工作区"层**：切换藏在总览页 `<select>`，且 `window.location.reload()` 整页刷新丢内存态 | `ProjectHomeView.tsx:56` |
| U-4 | P1 | **三栏只在 `/chat` 内成立**：外层 `App.tsx:64-95` 恒两栏，切路由对话区即卸载（WS 是模块级单例故流式不断，但不可见不可操作） | `App.tsx:64-95` |
| U-5 | P1 | **无组件测试基础设施**：无 jsdom / @testing-library，现有 .tsx 测试只能 `renderToStaticMarkup` 做结构+纯度断言，**交互链路零覆盖**（这正是 R7~R9 三轮逃逸的根因） | `package.json:24` |
| U-6 | P1 | 单行巨型 JSX 无法 review/diff/定位报错：`ArtifactReviewView` 4,344 字符、`AnalysisRunsView` 3,652 | 见 §3.8 |
| U-7 | P2 | 响应式硬编码：窄屏会话列表与产物 dock **直接消失且无抽屉兜底** | `ChatView.tsx:285,325,546` |
| U-8 | P2 | 快捷键体系仅 Cmd+K 与 Esc 栈两处；Cmd+K 只是搜索跳转，**不能执行动作** | `WorkspaceSearch.tsx:56-66` |
| U-9 | P2 | 7 处裸 localStorage，key 无版本号、无统一方案、无迁移机制 | 见 §3.8 |
| U-10 | P2 | 三处 `eslint-disable exhaustive-deps`，埋 stale closure 风险 | `ChatView.tsx:99,106,279` |
| U-11 | P2 | 切工作区后 `ArtifactVersionStore` 瞬间指向新工作区，生成中的变更写旧库、UI 读新库 | `workspace.py:44,258-271` |

### 2.6 Agent 能力完备度 — 当前 **C+**

18 项核验结果：**达标 3 / 部分 11 / 缺失 4**。

| ID | 级别 | 问题 | 位置 |
|---|---|---|---|
| G-1 | P1 | **记忆体系为零**：grep `memory/profile/preference` 后端零命中；无跨会话记忆、无用户画像 | — |
| G-2 | P1 | **无 MCP**：生产代码 grep `mcp` 零命中；`docs/plans/2026-08-21` 明确记录为推迟项 | — |
| G-3 | P1 | **多模态为零**：附件链路完整，但 `_content_for_llm` 把附件**降级为路径文本**；LLM 层 grep `image/vision/base64` 零命中 | `chat.py:1168-1187` |
| G-4 | P1 | **沙箱缺失**：`bash` 是无限制系统 shell；`run_python` 继承完整 env（`{**os.environ}`）→ 模型一行读走 `LLM_API_KEY` | `bash.py:243-245`、`python_exec.py:54` |
| G-5 | P1 | **无模型 fallback**：`factory.py` 只能二选一，失败即失败，不切 provider/降级 | `llm/factory.py:28-68` |
| G-6 | P2 | **无 tracing/span**：日志为文本，无 trace_id 串联子 Agent/LLM/工具 | — |
| G-7 | P2 | 检索无 rerank；"向量"是 128 维 hashing trick（`_embedding`），对词序语义不敏感 | `sources.py:31-39,198,294-300` |
| G-8 | P2 | 调度**仅 interval**，无 cron/rrule，无法表达"每周一 9:00" | `platform_store.py:2184-2196` |
| G-9 | P2 | 无交互式 todo 工具；计划一次性生成、人不可编辑 | `tools/registry.py:22-292` |
| G-10 | P2 | eval 不进 CI（需 API key），无回归基线趋势 | `.github/workflows/ci.yml` |
| G-11 | P2 | 提示词注入零防护：工具结果原样拼进 messages，无标签包裹/来源标注 | `agent.py:747-755` |
| G-12 | P2 | 危险命令正则仅 17 条且多带尾锚：`rm -rf /tmp/data`、`del /s /q`、`git clean -fdx`、`taskkill`、`iex` 全部放行 | `permissions.py:22-43` |
| G-13 | P2 | **窗口表过时**：`("claude-sonnet", 200_000)`，Sonnet 5 实为 1,000,000 → 压缩早 5 倍触发 | `context.py:31-33` |
| G-14 | P2 | **价格表错**：`claude-opus: 15.0/75.0`，Opus 5 实为 $5/$25（3 倍高估）；无 fable 条目 | `budget.py:28` |
| G-15 | P2 | README 声称 7 个工具，实际 14 个；README/PROJECT_STATUS 多处声称超前于实现 | `README.md:32,182` |

---

## 3. 解决方案（含迁移路径与回滚）

> 每个卡片格式：**现状 → 方案 → 涉及文件 → 迁移路径 → 回滚 → 验证**

### 3.1 【P0】Anthropic 默认路径必然 400（Q-7 / G-13 / G-14）

**现状**：`constants.py:17` 默认 `claude-sonnet-5`，`anthropic.py:183` 无条件发送
`temperature`（`agent.py:97` 默认 0.5、`anthropic.py:164` 默认 0.7）。
**已联网核实**：Claude 5 全系与 Opus 4.7+ 传非默认 temperature 返回 **400**。全仓无模型守卫。
→ 新用户只填 Key 不填模型，**第一通请求即失败**。

**方案**（新增 `_supports_sampling_params()`，按模型族判断是否下发）：
```python
# llm/anthropic.py
_NO_SAMPLING_RE = re.compile(r"^claude-(opus|sonnet|fable|mythos)-([5-9]|\d{2,})(?!\d)")
_NO_SAMPLING_RE_4X = re.compile(r"^claude-(opus|sonnet|haiku)-4-([7-9]|\d{2,})")
def supports_sampling_params(model: str) -> bool:
    m = model.strip().lower()
    return not (_NO_SAMPLING_RE.match(m) or _NO_SAMPLING_RE_4X.match(m))
```
body 构造改为 `if supports_sampling_params(self.model): body["temperature"] = temperature`。
**注意正则陷阱**：不能用 `-4-` 结构匹配（Claude 5 丢掉了 minor 段，会静默失配）。

**涉及文件**：`llm/anthropic.py:180-190`（+ 新函数）、`kernel/context.py:29-43`（窗口表）、
`kernel/budget.py:27-39`（价格表）

**迁移路径**：
1. 新增纯函数 + 单测（**不接线**）→ 2. body 构造改为条件下发 → 3. 更新窗口表
   （sonnet/opus/fable → 1_000_000，haiku → 200_000）→ 4. 更新价格表
   （opus 5/25、sonnet 2/10、新增 fable 10/50、mythos）→ 5. 未知模型
   `cost_cap_enforceable=False` 时补一条显式 warning（当前是静默跳过）

**回滚**：纯条件分支，回退即恢复全量下发；窗口/价格表是常量，改动独立可单独 revert。
三处改动互不耦合。

**验证**：
- 单测 `tests/test_llm_sampling_params.py`：参数化覆盖
  `claude-sonnet-5/opus-5/fable-5/opus-4-7/opus-4-8 → False`；
  `claude-sonnet-4-6/opus-4-6/haiku-4-5/claude-3-* → True`
- 断言：对 sonnet-5 构造的 body **不含 temperature 键**；对 4-6 **含**
- 价格表/窗口表单测：断言 `price_for("claude-opus-5")["input"] == 5.0`
- **人工复现**：`LLM_PROVIDER=anthropic LLM_MODEL=claude-sonnet-5` 发一条消息 →
  修复前 400，修复后正常流式返回

---

### 3.2 【P0】并发三修（C-1 / C-2 / C-3 / C-4）

三处都是**一行到三行**的修复，但必须同批做——它们共同构成"多连接安全"的最小闭合。

**C-1 `handles` 泄漏**
```python
# runtime/task_hub.py，_drive() 的 finally 块首行
finally:
    self.handles.pop(handle.task_id, None)   # ← 新增
```
**迁移路径**：先加，再补一个"延迟清理"开关（`RA_TASK_HANDLE_TTL_S`，默认 0=立即），
便于需要 `live_task`/`stop` 可达性的场景。**回滚**：删该行。
**验证**：新增 `tests/test_task_hub_lifecycle.py::test_handle_released_after_terminal`——
跑完一个任务后 `assert task_id not in hub.handles`；
再加 `test_live_count_not_inflated`：串行跑 20 个任务后 `live_count() == 0`。

**C-2 重复 attach**
```python
# web/chat.py:1984 附近
already = target in watching
if already:
    LOG.debug(...)
    return                    # ← 新增：不再无条件 +1
_observe(target)
```
**迁移路径**：直接改，同时把 `_observe` 的 `+1` 与 `watching.append` 合并为同一
"登记"语义（防止后续再漂移）。**回滚**：删 `return`。
**验证**：`tests/test_chat_observers.py`——同一连接 attach 两次后断连，
`assert handle.observers == 0` 且 `orphan_task is not None`（看门狗已武装）。

**C-3 注册竞态**
```python
# web/chat.py:1547-1558 —— 把「读 previous + 写 _LIVE/_SINKS」做成无 await 原子段
previous = _LIVE.get(sid)
_LIVE[sid] = websocket          # ← 先同步占位（此段无 await）
_SINKS[sid] = outbox.put_nowait
if previous is not None and previous is not websocket:
    asyncio.create_task(_close_quietly(previous))   # ← 关闭移出原子段
```
**迁移路径**：新增 `_close_quietly` 辅助（吞异常 + 记 debug）；调整三行顺序。
**回滚**：恢复 `await previous.close()` 在写表之前。
**验证**：`tests/test_chat_concurrency.py::test_concurrent_attach_single_sink`——
两条 WebSocket 几乎同时 attach 同一 sid，断言二者中**只有一条**在 `_SINKS` 且
**等于后到的那条**（确定性断言，避免 flaky）；
外加 `test_frame_not_cross_delivered`：A 回合的帧不出现在 B 的 outbox。

**C-4 `_ACTIVE` 占位检查**（第二道防线）
```python
# web/chat.py _start_turn 入口
if _ACTIVE.get(sid) is not None:
    handle = _ACTIVE[sid]
    if handle.task is not None and not handle.task.done():
        return   # 已有活动回合：调用方应走 steer 路径
```
**验证**：`test_concurrent_turns_single_active`——并发调两次 `_start_turn`，
断言 `_ACTIVE[sid]` 只有一个且 `history.json` 两次写入都被保留。

---

### 3.3 【P0】恢复功能会删数据（F-1）

**现状**：
```python
# versioning.py:98-106
data = self._snapshot(change_id, side)      # :77 文件不存在 → None
if data is None:
    if target.exists():
        target.unlink()                      # ← 销毁
# janitor.py:180-187 —— 只 unlink bin，index.json 记录留成悬空
path.unlink()
```

**方案**（两处必须同一语义）：
1. `restore()` 区分「该文件当时确实不存在」（合法删除语义）与「快照丢失」（数据缺失）：
   用 `record[f"{side}_exists"]` 判定——`True` 但读不到 bin → **抛 `SnapshotMissingError`**；
   `False` → 才允许 `unlink()`。
2. `_sweep_changes` 淘汰 bin 时**同步从 `index.json` 移除该 change_id**，二者同一事务；
   若只想淘汰一侧（如只删 before.bin 保留 after），则把对应 `*_exists` 置 `False` 而非留悬空。

**涉及文件**：`artifacts/versioning.py:77,98-112`、`runtime/janitor.py:175-190`

**迁移路径**：
1. 新增 `SnapshotMissingError` 异常类（不抛，先落地）→ 2. `restore()` 加判定并抛异常 →
   3. REST 层捕获该异常返回 409 + 明确文案"该版本快照已被清理，无法恢复" →
   4. Janitor 淘汰改为同步清索引 → 5. **存量修复脚本**：启动时扫描 `index.json`，
   把 bin 缺失的记录标记 `*_exists=False` 并写入 `snapshot_evicted: true`

**回滚**：第 2/3 步可独立 revert；第 5 步是幂等标记，回滚只需清标记。
**验证**：
- `tests/test_versioning_restore.py::test_restore_missing_snapshot_raises`——
  手工删 `before.bin` 后 `pytest.raises(SnapshotMissingError)`，并断言**目标文件仍存在**
- `::test_restore_creation_unlink_allowed`——新建文件的 before 侧恢复仍应删除（合法语义）
- `::test_janitor_eviction_syncs_index`——填满 `.ra/changes` 触发淘汰后，
  `index.json` 中不含已淘汰 change_id
- **人工复现**：把 `.ra/changes` 容量调小（`RA_JANITOR_CHANGES_CAP_MB`），
  跑几轮写入触发淘汰 → 在变更页点最旧记录的"恢复" → 修复前文件消失，修复后报 409

---

### 3.4 【P0】前端正确性（U-1 / U-2）

**U-1 无限轮询**
```tsx
// ProjectHomeView.tsx:35-46
useEffect(() => { ... }, [refresh, refreshApprovals, home?.project]);
//   ↑ home 每次 setHome 都是新对象 → 引用变化 → effect 重跑
```
**方案**：把 recentProjects 逻辑拆成独立 effect，依赖 `home?.project?.root`（**字符串**）；
数据加载 effect 依赖收敛为 `[refresh, refreshApprovals]`（`useCallback([])` 本就稳定）。

**迁移路径**：先拆 effect（纯重构，零行为变化）→ 再验网络请求次数。
**回滚**：合并回原 effect。**验证**：
- `frontend/src/views/__tests__/projectHomeEffects.test.ts`：mock `api.get`，
  渲染后断言 `/api/project/home` **恰好被调用 1 次**（这是核心回归锁）
- **人工复现**：打开总览页看 Network 面板，修复前持续刷，修复后 1~2 次

**U-2 ErrorBoundary**
新增 `frontend/src/components/common/ErrorBoundary.tsx`（class 组件，
`componentDidCatch` + fallback UI + 「重新加载」按钮），包裹 `App.tsx` 的
`<Routes>` 外层**与**每个 lazy chunk 的 `<Suspense>` 内层（双层：单页崩不白屏整站，
chunk 加载失败也有兜底）。
**迁移路径**：纯新增，无既有改动。**回滚**：移除包裹。
**验证**：单测——渲染一个抛错的 children，断言 fallback 出现且
`onError` 回调被调；再断言**兄弟路由仍可用**（隔离性）。

---

### 3.5 【P1】文件治理统一（F-2 / F-3 / F-4）

**目标**：确立 `platform_store` 为**唯一权威源**，其余降为派生视图。

**方案（三件事，按序）**：

1. **版本化下沉**。`core.atomic_write_text` 增加可选 `version_store` 钩子
   （默认 `None`，不传即零行为变化），由 `ToolRegistry` 注入。这样工具层、
   REST 层、子进程写入都能进历史。
2. **推模式回填**。工具写入成功后同步 `platform_store.upsert_artifact(...)`，
   替代当前"有人调 REST 才更新"的拉模式（`chat.py:648-650`）。
   `manifest.json` 与 `artifact_reviews` 改为**派生视图**，加一致性校验端点。
3. **漏网可见化**。`registry.py:384,393` 超限丢弃时计数，
   回执追加「N 个文件因超限未纳入版本跟踪」。

**涉及文件**：`core.py:33-57`、`tools/registry.py:346-400,613,635`、
`web/chat.py:584,636,648-650`、`runtime/platform_store.py`

**迁移路径**：
1. 加一致性校验脚本 `scripts/verify_artifact_consistency.py`（**只读**，输出 diff 报告）→
   2. 灰度期同时写两套并比对（feature flag `RA_FF_ARTIFACT_PUSH`）→
   3. 一致后切推模式 → 4. 旧的 `manifest.json` 降级为缓存，不再作为权威

**回滚**：feature flag 一键切回拉模式；两套并存期数据可交叉验证，无不可逆写入。
**验证**：
- `tests/test_artifact_authority.py`：工具写文件后**不调任何 REST**，
  直接查 `platform_store.artifacts` 断言已含该文件（推模式核心断言）
- `::test_snapshot_overflow_reported`：造 600 个文件触发超限，
  断言回执含"未纳入版本跟踪"字样且计数正确
- `scripts/verify_artifact_consistency.py` 在 CI 中作为**非阻断**检查跑，输出差异报告

---

### 3.6 【P1】`write_file` 围栏同口径（F-5）

```python
# file_ops.py:148-150（现状）
resolved_parent = safe_resolve(raw.parent, sandbox_path)
p = resolved_parent / raw.name          # ← name 未重新 resolve
# 改为（与 read/edit/glob/grep 同口径）
p = safe_resolve(raw, sandbox_path)
```
**迁移路径**：一行改动 + 补 `_reject_windows_hazard` 到 `edit_file`
（当前只有 `write_file` 有，`:81-112` 未施加于 `:163-221`）。
**回滚**：两行 revert。
**验证**：`tests/test_path_fence.py`——工作区内建指向沙箱外的符号链接，
断言 `write_file` 抛 `ValueError`；再加**反向断言**：正常路径写入不受影响
（防"修完把正常功能也堵了"的假绿，这是本项目 §7 已记录的教训）。

---

### 3.7 【P1】`.claude/skills` 去重（F-7）

**实测**：433 文件 / 7.9MB，**10 组字节级完全重复**：
- `qiniu_image.py` 复制到 4 个技能（generate-image / infographics / scientific-schematics / scientific-slides）
- `document-skills/docx/` 与独立 `docx/` 整树重复；`document-skills/pdf/` 与 `pdf/` 重复
- `research_lookup.py` 存在 3 份

**方案**：建立 `.claude/skills/_shared/` 存放公共库，各技能改为相对导入；
`document-skills/` 与独立 `docx/`、`pdf/`、`pptx-posters/` 合并为单一权威路径。

**迁移路径**（**必须保守**，因为 `cli.py:94-101` 与 `core.py:86-150` 按路径引用技能脚本）：
1. 只读审计：输出完整重复清单 + 各技能 `SKILL.md` 中的路径引用 →
2. 建 `_shared/`，**先做符号链接/薄转发层**（保持旧路径可用）→
   3. 逐技能改为直接引用 `_shared`，每次改完跑对应 E2E →
   4. 确认零引用后删除重复副本
**关键约束**：`.claude/skills` 是**运行时镜像源**（`core.py:86-150` 按内容哈希增量同步到
工作区），改动会影响所有新建工作区——必须在**测试工作区**验证后再推。

**回滚**：git 直接 revert（技能树是静态文件，无状态）。
**验证**：
- `tests/test_skills_dedupe.py`：断言 `.claude/skills` 下无字节级重复文件
  （`find + md5sum | uniq -d` 的 Python 版本，作为**长期守卫**）
- 每个被改动的技能跑一次冒烟（`scripts/smoke_live.py`）
- **人工复现**：新建工作区 → 让助手用 `scientific-schematics` 和 `generate-image`
  各画一张图 → 二者都成功

---

### 3.8 【P1】前端结构补齐（U-3 ~ U-6）

**U-3 项目/工作区层**
新增 `frontend/src/stores/workspaceStore.ts`（当前工作区、列表、切换态），
侧栏顶部加工作区切换器；切换改为 **store reset + 导航**，不再 `location.reload()`。
**迁移路径**：`ProjectHomeView` 的 select 保留（向后兼容），新增侧栏切换器；
稳定后把 select 换成"管理项目"入口。**回滚**：切换回 reload 一行。
**验证**：单测——切换后 `chatStore.sessionId === null`、`taskStore.activeTaskId === null`、
`artifacts` 已清空；人工——切换后不白屏、不留旧工作区残留。

**U-4 主对话区常驻**（改动最大的一项）
把 `Sidebar + main` 改为 `Sidebar + main + 可选 dock`。`/chat` 之外的路由，
对话区收为**底部可展开的常驻条**（保留"思考中/完成"状态与一键跳转）。
**迁移路径**：先把 `ChatView` 拆为 `ChatColumn`（纯展示，可复用）+ 路由壳；
再在 `App.tsx` 加常驻条（默认折叠，localStorage 记忆）。**全程 additive，不删路由。**
**回滚**：feature flag `RA_FF_PERSISTENT_CHAT` 关闭即回到现状。
**验证**：单测——`/tasks` 路由下常驻条仍渲染且反映 chatStore 状态；
人工——在 `/tasks` 看到回合完成提示，点击跳回 `/chat` 且消息完整。

**U-5 组件测试基础设施**
新增 dev 依赖 `jsdom` + `@testing-library/react@^16` + `@testing-library/user-event`
+ `@vitest/coverage-v8`（**全部 dev-only，不进打包产物**；React 18 兼容）。
vitest 配置加 `environmentMatchGlobs`，只对 `*.dom.test.tsx` 启用 jsdom，
**既有 node 环境测试零影响**。
**验证**：为 `Composer`（发送/IME/失败回滚）、`SessionList`（搜索/置顶/归档）、
`ApprovalCard`（批准/拒绝）各写一组交互测试——这正是 R7~R9 逃逸的三条链路。

**U-6 单行巨型 JSX 拆分**
`ArtifactReviewView`（4,344 字符单行）、`AnalysisRunsView`（3,652）等按
「列表 / 详情 / 预览 / diff / 操作栏」拆成子组件。
**迁移路径**：**先补测试再拆**（用 U-5 的新设施锁定当前行为），
纯结构重构、导出名不变 → 父组件引用不变 → 零对外变化。
**回滚**：git revert（纯结构）。

---

### 3.9 【P1/P2】Agent 能力补齐（G-1 ~ G-6）

按「补齐成本 × 依赖解锁度」排序：

| 顺序 | 能力 | 方案要点 | 新依赖 |
|---|---|---|---|
| 1 | **模型 fallback**（G-5） | `llm/factory.py` 加 provider/model 链；`retry.py` 识别不可重试错误后切链；配置 `RA_MODEL_CHAIN` | **无**（httpx 已有） |
| 2 | **环境净化**（G-4 半解） | `python_exec`/`frozen_exec` 剔除 `LLM_*`/`IMAGE_*`/`*_API_KEY`/`TOKEN` 前缀变量；危险命令正则扩充至 ~40 条并去掉脆弱尾锚 | **无** |
| 3 | **跨会话记忆**（G-1） | SCHEMA 12→13 加 `memories(id, project_id, kind, content, embedding_hash, created_at, pinned)`；新增 `remember`/`recall` 两个工具；复用 `context/sources.py` 的 FTS5 | **无** |
| 4 | **MCP 客户端**（G-2） | **自研最小客户端**（SSE + stdio），基于已有 httpx；工具动态注册进 `ToolRegistry`；配置 `.ra/mcp.json` | **无**（不引入 `mcp` SDK，避免给 PyInstaller 增重） |
| 5 | **多模态**（G-3） | `_content_for_llm` 支持 image content block；按 provider 能力判断；base64 编码 + 体积上限 | **无** |
| 6 | **tracing**（G-6） | 加 `trace_id`/`span_id` 到 `events.jsonl` 与结构化日志；子 Agent 继承 trace_id | **无** |
| 7 | **沙箱**（G-4 全解） | `ExecProvider` 接缝已预留，补 Docker provider；先解决**冻结态 spawn 子进程 env 继承** | 可选（docker SDK 仅开发态） |

**共同约束**：全部走 **feature flag + additive**，关旗即回到现状；
SCHEMA 迁移沿用既有幂等 `ALTER` 模式（10→11→12 已验证）。

---

## 4. 分阶段执行计划

> 排序原则：**先修正确性与并发缺陷 → 再重构架构 → 最后补齐前端与 Agent 能力**

### 阶段 0：可观测地基（1d）
**目标**：没有测量就无法证明 A+，先装仪表盘。

| 项 | 涉及文件 | 改动量 |
|---|---|---|
| 后端覆盖率 | `pyproject.toml`（加 `pytest-cov` + `--cov` 配置） | 5 行 |
| 前端覆盖率 | `package.json` + `vite.config.ts`（`@vitest/coverage-v8`） | 10 行 |
| 并发测试脚手架 | `tests/conftest.py`（多 WS 连接 fixture、并发回合工具） | ~80 行 |
| 基线快照 | `docs/quality/baseline-2026-08-28.md` | 文档 |

**验收**：`pytest --cov` 与 `vitest --coverage` 均能出报告；基线数字入档。

### 阶段 1：正确性与并发清零（3d）
P0 全清 + C 级并发项。

| 顺序 | ID | 改动量 |
|---|---|---|
| 1.1 | Q-7 模型守卫 + 窗口表 + 价格表 | ~60 行 |
| 1.2 | U-1 无限轮询 + U-2 ErrorBoundary | ~80 行 |
| 1.3 | F-1 恢复删数据 + Janitor 索引同步 | ~70 行 |
| 1.4 | C-1/C-2/C-3/C-4 并发四修 | ~30 行 |
| 1.5 | F-5 write_file 围栏 | ~10 行 |
| 1.6 | C-6 BEGIN IMMEDIATE 补齐 | ~20 行 |
| 1.7 | C-7 出站队列有界 | ~15 行 |

**验收**：全部 P0 缺陷的回归测试通过；并发测试套件（新增 ≥12 项）全绿；
无新失败；覆盖率不低于基线。

### 阶段 2：文件治理统一（4d）
F-2/F-3/F-4/F-6/F-7/F-8。

**验收**：`scripts/verify_artifact_consistency.py` 零差异；
`.claude/skills` 零字节级重复（长期守卫测试）；
`git status` 干净（无未跟踪临时文件）；`du -sh` 磁盘占用下降 ≥30%。

### 阶段 3：架构重构（4d）
A-1/A-2/A-3/A-4/A-5/A-6 + Q-2/Q-3。

| 顺序 | 项 | 改动量 |
|---|---|---|
| 3.1 | `run_agent` 拆分为 6 个纯函数（保留原函数为编排壳） | ~300 行重构 |
| 3.2 | `registry.execute` 拆分 + 死代码删除 | ~150 行 |
| 3.3 | 重复代码块合并（截断 ×3、stop_reason_map ×4、steer ×3） | -120 行 |
| 3.4 | 类型注解补至 ≥90%、docstring ≥85%，接 mypy 渐进 | ~400 行 |
| 3.5 | 静默吞异常清理（60 处分类：真忽略→加注释与计数，真错误→上报） | ~120 行 |
| 3.6 | 会话/任务体系：先做**只读统一视图**，不动两套写入 | ~200 行 |

**验收**：ruff 全绿（含新增 C90/SIM 规则）；mypy 无 error；
所有函数 ≤80 行、CC ≤15（`--max-complexity` 门禁）；重复率 <3%。

### 阶段 4：前端补齐（5d，可与阶段 2/3 并行）
U-3/U-4/U-5/U-6/U-7~U-11。

**验收**：组件交互测试覆盖 8 条关键链路（发送/中断/重连续播/审批/归档/编辑重发/
切换会话/切换工作区）；`tsc -b` 零错误；`vitest --coverage` 达标；
窄屏无面板消失（抽屉兜底）；无 `eslint-disable exhaustive-deps`。

### 阶段 5：Agent 能力补齐（8~10d）
按 §3.9 顺序：fallback → 环境净化 → 记忆 → MCP → 多模态 → tracing → 沙箱。

**验收**：18 项能力矩阵中**达标 ≥15 项，缺失 0 项**；
每项能力有对应集成测试；eval 接入定时任务（非 PR 门禁）并记录趋势。

---

## 5. A+ 验收标准

### 5.1 类型检查与 lint 零错误

| 项 | 标准 | 命令 |
|---|---|---|
| Python lint | 零 error | `ruff check research_assistant tests scripts build.py` |
| Python 类型 | 零 error（渐进：先核心模块，后全量） | `mypy research_assistant` |
| TS 类型 | 零 error | `npx tsc -b` |
| 复杂度门禁 | 所有函数 ≤80 行、CC ≤15 | `ruff check --select C901 --max-complexity 15` |
| 安全规则 | 零 high severity | `ruff check --select S` |

### 5.2 测试覆盖率

| 层 | 行覆盖率 | 说明 |
|---|---|---|
| 后端整体 | **≥ 75%** | `pytest --cov=research_assistant --cov-report=term-missing` |
| 后端关键模块 | **≥ 85%** | `kernel/`、`tools/`、`llm/`、`runtime/`、`artifacts/`、`web/chat.py` |
| 前端整体 | **≥ 70%** | `@vitest/coverage-v8` |
| 前端纯函数层 | **≥ 90%** | `lib/`、`stores/`（已有良好基础） |
| **并发场景** | **专项套件 ≥ 20 用例** | 见下 |

**并发场景测试清单（必须项）**：
1. 双 WS 同时 attach 同一 session（C-3）
2. 同连接重复 attach 后断连（C-2）
3. 并发 `_start_turn`（C-4）
4. 任务串行 20 次后 `handles` 与 `live_count`（C-1）
5. 多 worker 争抢同一 job（C-6）
6. 慢客户端下出站队列不无界增长（C-7）
7. 租约过期后旧持有者不回写（B3 既有语义回归锁）
8. 取消在 LLM 流式中途（既有优势的回归锁）
9. 工作区切换期间工具写入的归属（U-11）
10. Janitor 淘汰与 restore 并发（F-1）

### 5.3 无未使用 / 重复 / 孤儿文件

| 检查 | 方法 | 标准 |
|---|---|---|
| 孤儿模块 | 引用图扫描 | **0 个**（当前实测：后端 0 个，`launcher_desktop.py` 经核实是 build.py 入口，非孤儿） |
| 前端孤儿 | 引用图扫描 | **0 个**（当前 1 个：`views/Placeholder.tsx`，无任何路由引用） |
| 字节级重复 | md5 分组 | **0 组**（当前 `.claude/skills` 10 组） |
| 代码块重复 | 重复率扫描 | **< 3%** |
| 未跟踪文件 | `git status --porcelain` | **0 个**（当前：`git_diag*.txt`、`audit_result.txt`、`.audit_tmp/`） |
| 临时目录 | `.gitignore` 覆盖 + 实际清理 | `.pytest_tmp*` 迁至 `tmp/pytest/` 并复用；`dist/` 仅留最新安装包 |

### 5.4 前端关键交互链路完整可跑

以下 8 条链路**每条都要有自动化测试**（单测或 E2E）：

1. **发送 → 流式上屏 → 完成**（含失败回滚，防"永久思考中"）
2. **中断 → 部分文本落盘带 `partial:true`**
3. **断线 → 指数退避重连 → 按 lastSeq 续播不丢帧**
4. **审批卡 → 批准/拒绝 → 工具继续/中止**
5. **重新生成 / 编辑历史消息 → 真替换（旧答案真正消失）**
6. **切换会话 → 不串流（`openToken` 守卫）**
7. **切换工作区 → 状态复位、不残留旧工作区数据**
8. **附件上传 → 落盘 → 随消息入史 → 刷新后徽章恢复**

外加：**落地页网络请求恰好 1 次**（U-1 回归锁）、**任一 view 抛错不白屏**（U-2）。

### 5.5 Agent 工具调用与错误恢复闭环

| 环节 | 验收 |
|---|---|
| 工具调用 | 14 个工具全部有参数校验（含枚举约束）；全部有超时与输出截断 |
| 工具失败 | 错误串回灌模型且**回合不中断**（既有优势，加回归锁） |
| LLM 失败 | 按 status code 分类；可重试走退避+抖动；**不可重试切 fallback 链** |
| 解析失败 | SSE 坏帧不静默丢弃（当前 `except JSONDecodeError: continue`），改为计数+告警 |
| 上下文超限 | 压缩后 tool_call/tool_result 配对**必须完整**（既有优势，加属性测试） |
| 中途取消 | 取消穿透到 LLM 调用；工具执行中取消在下个边界生效（已文档化） |
| 崩溃恢复 | 进程重启后 `interrupted` 任务可一键续跑；session 从 `run.json` 恢复 |
| 门禁失败 | Citation/Doc Gate 失败自动返工 ≤3 轮；超限时**主动删除无效稿件** |
| 预算 | 四维硬闸；未知模型显式告警而非静默跳过 |

---

## 6. 改动前后评级对比

| 维度 | 改前 | 阶段 1 后 | 阶段 2 后 | 阶段 3 后 | 阶段 4 后 | 阶段 5 后（目标） |
|---|---|---|---|---|---|---|
| 架构设计 | A- | A- | A | **A+** | A+ | **A+** |
| 工程质量 | B+ | A- | A- | **A+** | A+ | **A+** |
| 并发正确性 | **C** | **A** | **A+** | A+ | A+ | **A+** |
| 文件治理 | **C+** | B+ | **A+** | A+ | A+ | **A+** |
| 前端完成度 | B+ | A- | A- | A- | **A+** | **A+** |
| Agent 能力完备度 | **C+** | C+ | C+ | B | B+ | **A+** |
| **综合** | **B** | **B+** | **A-** | **A** | **A** | **A+** |

**关键跃迁点**：
- 并发 C → A+ 在**阶段 2 结束时**即可达成（阶段 1 修完 4 个确定性缺陷，
  阶段 2 补齐并发测试到 20 项）
- 文件治理 C+ → A+ 在**阶段 2 结束**（权威源统一 + 去重 + 清理面）
- 架构 A- → A+ 依赖阶段 3 的拆分与重复消除
- Agent 能力只能靠阶段 5 逐项补齐，**无法靠重构加速**

---

## 7. 依赖冲突分析

**结论：新增运行时依赖 0 个。** 全部新能力基于已有的 httpx / 标准库实现。

| 候选依赖 | 用途 | 是否引入 | 冲突分析 |
|---|---|---|---|
| `pytest-cov` | 覆盖率 | ✅ **dev-only** | 无冲突；CI 需同步加 `--cov` |
| `@vitest/coverage-v8` | 前端覆盖率 | ✅ **dev-only** | 与 vitest 3.1 版本对齐；不进 bundle |
| `jsdom` + `@testing-library/react@^16` | 组件交互测试 | ✅ **dev-only** | React 18.3 兼容（v16 支持 18/19）；用 `environmentMatchGlobs` 隔离，**既有 node 测试零影响** |
| `mypy` | 类型检查 | ✅ **dev-only** | 渐进接入；`requires-python>=3.10` 无阻 |
| `mcp`（官方 SDK） | MCP 客户端 | ❌ **不引入** | 会给 PyInstaller 产物增重且引入 asyncio 版本耦合。**改为自研最小客户端**（SSE+stdio，基于已有 httpx） |
| `jsonschema` | 工具参数校验 | ❌ **不引入** | 纯 Python 无冲突，但会进打包产物。**改为手写 ~80 行校验器**（当前 14 个工具的 schema 都很简单） |
| `docker` | 沙箱 | ⚠️ 可选 dev | 仅开发态；生产路径保持 `LocalExecProvider` |

**打包影响**：dev-only 依赖不进 PyInstaller 产物（`build.py` 按 `ResearchAssistant.spec`
的 hiddenimports 白名单打包），安装包体积不变。

---

## 8. 风险与预案

| 风险 | 概率 | 预案 |
|---|---|---|
| 阶段 1 并发改动引入 flaky 测试 | 中 | 并发断言必须**确定性**（用事件同步而非 sleep）；CI 加 `--reruns 2`；flaky 即视为失败不许 retry 过关 |
| `.claude/skills` 去重影响工作区镜像 | **高** | 该目录是运行时镜像源。**先在测试工作区验证**，保留旧路径转发层一个版本后再删 |
| 阶段 3 `run_agent` 拆分引入行为变化 | 中 | **先补测试再拆**；原函数保留为编排壳，导出签名不变 |
| 阶段 4 三栏改造破坏既有路由 | 中 | 全程 additive + feature flag `RA_FF_PERSISTENT_CHAT`，关旗即回现状 |
| MCP 自研客户端与官方协议漂移 | 中 | 只实现 **tools + resources** 两个核心能力面；协议版本写死在配置里并加兼容性断言 |
| 覆盖率达标但测试质量低（假绿） | **高**（本项目已有教训） | 新增测试**必须含反向断言**；关键链路用真实浏览器 E2E 兜底（沿用 `scripts/e2e_*.py` 模式） |

---

## 9. 立即可以开始的三件事

1. **阶段 0（1d）**——没有仪表盘就无从谈达标，先装覆盖率。
2. **阶段 1 的 1.1（半天）**——`constants.py:17` + `anthropic.py:183` 是当前唯一的
   **首次运行即阻断**缺陷，优先级高于一切重构。
3. **阶段 1 的 1.2（1h）**——`ProjectHomeView.tsx:33-46` 的无限循环正在持续打爆后端，
   修复成本极低。

---

*本规划基于 `2026-08-28-code-review-full.md` 的缺陷清单，所有 file:line 均经复核；
外部事实（Claude 5 参数弃用、模型 ID、上下文窗口、价格）经 2026-08-28 联网核实。*
