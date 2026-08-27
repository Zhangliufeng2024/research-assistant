# PROJECT_STATUS — 研究助手 (research-assistant-v3)

> **聊天耐久化增量（2026-08-26，R16）**：会话回合与 WebSocket 连接彻底解耦——「断连即取消」废除。
> **后端**（`web/chat.py`）：回合状态收敛进 `_TurnHandle`（预算/审批/steer 队列/环形缓冲/partial_text），
> 断连仅减少观察者计数；孤儿看门狗宽限 `RA_CHAT_ORPHAN_GRACE_SECONDS`（默认 900s）到期先协作停止、
> 再 30s 硬取消兜底；帧环形缓冲 `FRAME_RING_CAP=4000` + **会话内单调 seq**，重连 `attach{after}` 按
> seq 续播（`replay_begin/replay_end/replay_empty`）；回复全路径落盘，被打断的回答带 `partial:true`
> 不丢字。新增三个历史治理端点：`POST …/truncate`、`PATCH …/messages/{i}`（编辑用户消息）、
> `POST …/attachments`（multipart 上传落 `outputs/<sid>/uploads/`，围栏校验）；`_read_history`
> 透传 `attachments`/`partial` 结构化扩展字段。
> **前端**：断线指数退避自动重连（~28s 放弃转手动「重连」按钮），重连成功按 lastSeq 续播；
> 附件 chips（选择/拖拽/粘贴，单条 ≤8 个、总量 50MB）随消息入史并在刷新后恢复徽章；
> 重新生成/编辑改为**真替换**（服务端 truncate + 本地同步裁剪 + 重发，旧回答真正消失而非追加平行答案），
> 草稿态/离线回落保守重发。协议文档同步至 `docs/protocol.md §10`。
> **真实浏览器 E2E 再立功**：新增 `scripts/e2e_smoke_r16.py`（断连回放/真替换/附件链路/刷新恢复五断言），
> 首轮即抓出三个协议级测试集体漏掉的缺陷——① seq 每回合归零致重连后整回合帧被游标滤掉；
> ② result 帧先于收尾清理到达，「立刻追问」被转成无人消费的幽灵 steer；③ `_read_history`
> 清洗扩展字段致每回合写回都丢附件/打断标记。均已修复并固化回归测试
> （`tests/test_chat_durability.py`，17 用例）。R13–R15（流式合帧 R14-S、切换竞态 R13-D、
> 审批超时兜底 R13-C、首导向极性修复 R15 等）以代码内标注为准，此处补记。
> 当前全量 Python **941 passed / 1 skipped**，前端 Vitest **213 passed**（24 文件），tsc/Vite 构建通过，ruff 全绿（2026-08-27 复核）。


> **科研操作系统增量（2026-08-24）**：平台已从“任务/论文生成器”扩展为可追溯的
> 研究对象内核。SQLite WAL 现在持久化研究问题/假设、主张、证据链接、决策、可复现
> 运行和 provenance 图；新增 DurableScheduler 租约队列与“研究工作台”前端。详见
> `docs/protocol.md §5.4`。旧论文 pipeline、citation/doc gates、ArtifactStore 和
> 产物变更恢复保持不变。

> **统一 Agent 工作空间增量（2026-08-24）**：按 `plan260824.md` 完成第一轮可运行
> 重构。数据库 schema v10 新增 Thread/Turn/AgentItem/AgentRun、QualityItem、ArtifactReview、通知、资源租约字段和持久化 Agent 审批收件箱；
> 默认首页改为 Project Home，新增研究线程、证据矩阵和产物审阅入口。旧 chat/task/ws
> 协议继续兼容，durable task 会自动映射到统一线程时间线。

> **Supervisor / 复现运行增量（2026-08-24）**：通用 workflow ready 节点已接入
> `AgentSupervisor`，新增并发上限和 Agent 生命周期事件；schema v10 包含 `analysis_runs`、`agent_runs` 与跨进程资源租约，
> 前端增加运行队列和分析运行面板。

> **科研闭环增量（2026-08-24）**：产物 Inspector 已接入真实预览、变更 diff、provenance、
> Citation/Doc Gate 摘要和“要求 Agent 修改”回写；分析运行支持比较与后台复现；研究包支持
> 安全导出/导入；节点人工跳过/接管和审批 request_id 防迟到回执已接入。当前全量 Python
> **717 passed / 1 skipped**，前端 Vitest **60 passed**，TypeScript/Vite 构建通过。

> 交接文档 · 更新于 2026-08-24 · 已发布版本 **v3.4.0**（commit `a773fbb`；
> R12：执行契约 + 文件双轨制 + 产出 dock + 草稿入列）。真实 UI E2E 六断言全过（§5）；安装包
> `dist/ResearchAssistant_setup_3.4.0.exe` 静默装/卸验证通过。
> 下一步：目标机验证 v3.4.0（无 Python 机器画图 / 产物归巢 / dock）。

---

## 1. 当前目标

桌面端 AI 研究助手（PyInstaller + WebView2 单机应用，FastAPI 后端 + React 前端）。
主线演进到 **R12/v3.4.0**：把目标机验证暴露的「打包态执行环境契约缺失」缺陷做成产品保证，
并落地用户确认的三项产品诉求——文件双轨制、右侧产出 dock、新会话草稿入列。

## 2. 已完成内容（R6 → R10）

| 轮次 | 版本 | 内容 |
|---|---|---|
| R6 | 3.2.x | 设置页图形化模型配置 |
| R7 | 3.3.0 | React 18 前端重写 + pywebview 桌面壳（旧 ws.js 移植为 lib/ws.ts，**此处引入本轮根因**） |
| R8 | 3.3.1 | 全局配置迁移 `%APPDATA%/ResearchAssistant/.env`、免选夹直入、配置即生效 |
| R9 | 3.3.2 | LLM 调用监督体系化（两阶段看门狗/墙钟/可打断）、前端失败如实上报、等待横幅、结构化会话日志 |
| R10 | 3.3.3 | **定位并修复真正根因**：ws.ts 从未把 socket 登记进 `socks` 表；新增真实 UI 路径 E2E |
| R11 | 3.3.x（并入 v3.3.4 未发） | §6.3 会话列表日期显示（epoch 秒被当毫秒→「1970年1月22日」）；§6.4 空会话治理（三层：后端列表清退零轮次目录 / 前端失败补偿删除 / 工作区切换复位会话态）；§6.5 等待横幅提示 `RA_LLM_FIRST_BYTE_TIMEOUT` |
| R12 | **v3.4.0（已发）** | **P1 冻结执行契约四层防御**（A1 契约函数注入三 choke point / A2 `_FIGURE_PROMPT` 重写 / A3 frozen_exec 注入 `run_script`+`WS` / A4 bash python 拦截守卫 / A5 desktop 入口防线+`RA_ALLOW_SHELL_OPEN` / A6 run_python 工具描述）；**P2 文件双轨制**（chat 产物 `outputs/<sid>/`、write_anchor 写入归巢、任务侧仅加 anchor 不动 exec_cwd、清退/删除配对删 outputs）；**P3 右侧产出 dock**（ArtifactsPanel 树+行内预览+打开文件夹，ChatView/TasksView 接线，折叠记忆跨页共享）；**P4 新会话草稿入列** |

R9 的全部后端加固经审计确认有独立价值（真实存在的挂死/不可打断缺陷），但用户侧
主因是 R10 的前端一行缺失——R7 重写时 `wsConnect` 创建 WebSocket 后未写入 `socks`，
导致 `wsSend`/`wsConnected` 永远失败：会话首条消息、steer、审批回执、停止、任务
start 全部发不出去。服务端握手正常却等不到帧（用户 desktop.log 佐证：`会话连接建立`
之后无 `回合开始`），前端表现为永久「思考中」（≤3.3.1）或「无法建立与服务端的连接」
（3.3.2 兜底文案）。

## 3. 关键技术决策

1. **两阶段 LLM 看门狗**（agent.py `_ActivityWatchdog`）：
   首字节前用短窗 `RA_LLM_FIRST_BYTE_TIMEOUT`（默认 60s，此前首字节前静默要等满
   heartbeat 300s 且绕过重试）；有心跳后按静默窗续期；另设单次尝试墙钟
   `RA_LLM_ATTEMPT_WALL_TIMEOUT`（默认 1800s）防 keepalive 滴流无限续期。
2. **监督置于重试循环内**：watchdog 以 `watchdog=` 参数注入 `_llm_call_with_retry`
   的单次尝试——`HeartbeatTimeoutError` 落入正常重试分类（retryable），不再炸穿循环。
3. **停止必须可打断在途调用**：`_cancelable`/`_TurnCancelled` 包装，cancel_event
   置位立即中断挂死中的 LLM 调用（旧实现只在轮次边界检查）。
4. **乐观 UI 必须有失败回滚**：前端 `applyUserMessage` 先置 running，任何发送失败
   路径必须经 `applySendFailure` 复位为 error——否则界面永远「思考中」。
5. **设置页「测试连接」与会话同路径**：探测带 `on_chunk` 走 stream:true，消除
   「测试通过、会话挂起」的流式/非流式错位。
6. **WebView2 强制 `--no-proxy-server`**（desktop.py）：WebView 只访问本机回环，
   系统代理对它无用且可能在 PAC 环境拦截回环 WS。
7. **发版必跑真实 UI 路径 E2E**（本轮最大教训）：mock 掉 ws 层的 vitest 与裸
   websocket 直连的后端 E2E 对前端状态机 bug 完全盲——R7~R9 三轮逃逸即证明。
   脚本见 §7。
8. **`/ws/chat` 双挂载保留**（app.py：带 `/api` 前缀 + 裸路径各挂一次）：前端硬编码
   裸路径，protocol.md §10 有约定，勿在重构中删除。
9. **执行契约四层防御**（R12/P1，详见 protocol.md §11）：提示层 addendum（冻结态禁裸
   python、指路 run_python/run_script/WS）→ bash 拦截层（冻结态逐段检查 python/pip 调用，
   不 spawn 直接给中文指引）→ frozen_exec 运行时（子进程注入 `run_script`/`WS`）→
   desktop 入口防线（文件参数 exit 2 + 定向文案）。模型自创 `subprocess([sys.executable,…])`
   这类「临场发挥」从根上封死。
10. **write_anchor 语义 = 相对写一律归巢**（R12/P2）：anchor 设置时 write_file 相对路径
    解析到 anchor（仍过围栏），edit_file 保持根解析——「改共享文件」响亮正确、会话永不
    静默覆写共享文件；成功回执回显最终绝对路径闭环读写往返。会话 registry
    `work_dir=根, write_anchor=exec_cwd=outputs/<sid>`；任务流水线只加
    `write_anchor=<paper_dir>` 不动 exec_cwd（阶段提示词全绝对路径，CWD=根行为保持）。
11. **connected 帧 outputs_dir 是 dock 权威源**：REST 列表的 outputs_dir 在工作区切换后
    会错接到另一工作区同名目录（tree/file 端点跟随进程 cwd），只作恢复期兜底。
12. **零轮次清退配对删除 outputs/<sid> 安全**：零轮次 ⇒ 从未执行工具 ⇒ 产物目录不可能
    含用户数据；孤儿 outputs 目录惰性不清扫。

## 4. 修改过的核心文件

### R12（v3.4.0）
- `research_assistant/core.py` — **A1**：`execution_contract_addendum()` 按 `sys.frozen`
  返回冻结契约/开发态一行；注入 `config.build_system_instructions`、pipeline
  `_run_stage_agent`、chat `_chat_system_instructions`、旧 orchestrator 助手四处
- `research_assistant/pipeline/orchestrator.py` — **A2**：`_FIGURE_PROMPT` 重写为
  matplotlib-via-run_python 主路径 + generate_schematic.py 经 run_script 次路径，删 nvidia/裸 python
- `research_assistant/tools/frozen_exec.py` — **A3**：子进程 globals += `WS` 与
  `run_script(path, argv=None)`（swap sys.argv/__name__/__file__/sys.path[0]，finally 恢复）；
  `_child_main` 第 4 参 workspace_root pickle 传递
- `research_assistant/tools/exec_provider.py` / `python_exec.py` — run_python 加性 kwarg
  `workspace_root=None` 全链转发；`tools/registry.py` — **B3**：`write_anchor`/`exec_cwd`
  参数，bash/run_python cwd 注入 `exec_cwd or work_dir`，run_python 分支恒传
  `workspace_root=self.work_dir`，write_file 分支注入 anchor，工具描述更新（A6）
- `research_assistant/tools/file_ops.py` — **B2**：write_file 加 write_anchor 参
  （相对一律 join(anchor)，回执回显最终绝对路径）；edit_file 根解析不变
- `research_assistant/tools/bash.py` — **A4**：`_segments`/`_is_python_invocation` 纯函数 +
  冻结态拦截返回中文指引
- `research_assistant/desktop.py` — **A5**：`workspace_arg_error()` 分类矩阵（文件→定向文案/
  非目录→现文案，exit 2 不变）+ `RA_ALLOW_SHELL_OPEN=1` setdefault
- `research_assistant/session/store.py` — **B1**：SessionState += `outputs_dir: str = ""`
- `research_assistant/web/chat.py` — **B4**：`OUTPUTS_SUBDIR`/`_outputs_root`；WS 连接即
  mkdir outputs/<sid> 并落盘；registry 三参装配；connected 帧 += `outputs_dir`；
  `_session_summary` += `outputs_dir|null`；清退/删除配对删 outputs；POST 不建目录；
  会话系统提示双目录口径（`_chat_system_instructions(work_dir, outputs_dir)`）
- `research_assistant/pipeline/runner.py` — **B5**：`_tools_for`/`_run_stage_agent` 线程化
  write_anchor，`_stage_kwargs` 传 paper 目录
- `research_assistant/api.py` — 单代理 ToolRegistry 加 write_anchor=paper 目录
- `frontend/src/lib/artifacts.ts`(+test) — **C1**：normalizeArtifactPath /
  candidatePreviewPaths（anchor 优先序+去重）/ IGNORED_TREE_PREFIXES / dock 折叠偏好 helpers
- `frontend/src/components/chat/FilePreview.tsx` — **C2**：预览主体从 Modal 抽出（候选序回退）；
  Modal 退化为遮罩壳
- `frontend/src/lib/types.ts` / `protocolChat.ts`(+test) — **C3**：ChatState.outputsDir、
  SessionSummary.outputs_dir、connected 帧归约
- `frontend/src/components/chat/ArtifactsPanel.tsx` — **C4**：懒加载树+行内预览+刷新+
  打开文件夹+空态（emptyRootHint 可定制）；ChatView/TasksView 接线（C5/C6：dockRoot 权威源
  链、phase 离开 running 自增 refreshKey、折叠细条记忆跨页共享、TasksView 运行行选中高亮）
- `frontend/src/components/chat/SessionList.tsx` / `Composer.tsx` / `views/ChatView.tsx` —
  **P4 草稿入列**：draftActive 高亮草稿行置顶（点击 focusSignal 聚焦输入框）、✚ 按钮草稿期置灰
- `frontend/vite.config.ts` / `src/lib/version.ts`(+test) / `App.tsx` / `tsconfig.json`
  （resolveJsonModule）— **页脚版本同源化**：`__APP_VERSION__` 构建期注入 package.json，
  替换 App.tsx 自 v3.3.0 漂移的硬编码「v3.3.0」（E2E 截图暴露）
- `docs/protocol.md` — §2/§7/§8/§10.1/§10.2/§10.3/§10.4 更新 + 新 §11 执行环境契约
- 测试：`tests/test_core.py`(TestExecutionContract)、`test_frozen_exec.py`(TestRunScriptHelper)、
  `test_tools.py`(TestBashPythonGuard/TestWriteAnchor)、`test_desktop.py`、
  `test_exec_provider.py`、`test_pipeline.py`(TestStageWriteAnchor)、`test_web_api.py`、
  `test_chat_api.py`(TestChatOutputsDir ×9 / TestChatSystemInstructions)

### R11（体验治理，待发版）
- `frontend/src/lib/format.ts` — **§6.3 核心**：`toMillis` 归一（<1e11 视为 epoch 秒 ×1000）；契约本就是秒（protocol.md:189），是前端违反了它。SessionList/TasksView 共用此口，一并修复
- `frontend/src/lib/__tests__/format.test.ts` — 新增 8 项（含「30 天前不得渲染成 1970 年」症状锁死）
- `research_assistant/web/chat.py` — **§6.4 后端**：`_sweep_zero_turn_sessions`（列表前清退零轮次且 >1h 的目录；安全性论证：用户消息回合开始前先落盘，零轮次 ≡ 从未收到用户帧）+ `ZERO_TURN_TTL_S`
- `tests/test_chat_api.py` — `TestZeroTurnGc` 新增 3 项（过期清退/新建保留/有对话保留）
- `frontend/src/stores/chatStore.ts` — **§6.4 前端**：`discardJustCreated`——POST 建目录后连接失败或帧未发出时补偿删除**本次新建**目录并复位 sessionId
- `frontend/src/stores/__tests__/chatStore.test.ts` — 新增 5 项编排回归（含「复用既有会话失败绝不误删」「steer 不碰目录」）
- `frontend/src/views/ChatView.tsx` — 工作区切换 `onSwitched` 先 `newSession()` 复位（防旧 sessionId 在新工作区触发服务端幂等重建空目录）；§6.5 等待横幅追加 `RA_LLM_FIRST_BYTE_TIMEOUT=30` 提示（全局 .env 会 load_dotenv(override=True)，提示可操作）
- `docs/protocol.md` — §10.2 列表接口补充清退行为说明

### R10（根因修复，commit `18e7aa4`）
- `frontend/src/lib/ws.ts` — **核心修复**：创建后 `socks.set(channel, sock)`；
  `onclose` 改身份守卫删除（防重连竞态下旧 socket 迟到的 onclose 误删新连接登记）
- `frontend/src/lib/__tests__/ws.test.ts` — 新增 6 项回归（登记后可达/URL 拼装/
  帧路由/重连竞态/断开清理/未开先断报 error）
- 版本四处：`pyproject.toml`、`research_assistant/__init__.py`、`packaging/installer.iss`、`frontend/package.json`
- `research_assistant/web/static/`（前端产物重建）

### R9（监督与如实上报，commit `083f7e6`）
- `research_assistant/agent.py` — 两阶段看门狗、`_cancelable`、每尝试监督
- `research_assistant/retry.py` — `get_first_byte_timeout`/`get_attempt_wall_timeout`（env：`RA_LLM_FIRST_BYTE_TIMEOUT`、`RA_LLM_ATTEMPT_WALL_TIMEOUT`；既有 `RA_MAX_RETRIES`=3、`RA_RETRY_BASE_DELAY`=5、`RA_HEARTBEAT_TIMEOUT`=300）
- `research_assistant/constants.py` — `HTTP_CONNECT_TIMEOUT_SECONDS` 30→15s；两个新超时默认值
- `frontend/src/lib/protocolChat.ts` — `applySendFailure`；`frontend/src/stores/chatStore.ts` — `failOffline` 兜底
- `frontend/src/lib/waitHint.ts`(+test) / `views/ChatView.tsx` — running 超 20s 无输出显示等待横幅
- `research_assistant/web/chat.py` — 会话生命周期结构化日志（会话连接建立/回合开始/回合结束/回合失败/断开/异常）+ 网络类错误追加中文排查指引
- `research_assistant/web/settings.py` — 流式对称探测；`research_assistant/tools/file_ops.py` — glob/grep 移入 `asyncio.to_thread`；`research_assistant/llm/errors.py` — HeartbeatTimeoutError 带阶段标签
- `tests/test_llm_supervision.py` — 新增 8 项监督回归

## 5. 测试与验证结果

本轮（schema v10，从 v9 幂等迁移）新增并验收：持久化审批收件箱、AgentRun、项目活动流、输入 schema/runtime 环境变化检测、项目依赖锁、跨进程资源租约、真实 source upload、
全局 Ctrl/Cmd+K 项目搜索、Agent 协作状态面板、导入 skip/overwrite/rename 冲突策略、删除资料后的
source_integrity 风险回写，以及 Citation/Doc/复现门禁失败时禁止产物 accepted。真实浏览器全流程脚本
`scripts/e2e_research_os.py` 输出 `[UI-E2E-RESEARCH-OS] PASS`；合成性能脚本
`scripts/perf_research_os.py` 输出 `[PERF-RESEARCH-OS] PASS`。

- **pytest**：717 passed / 1 skipped（当前全量回归；唯一 warning 是 test_utils docx 测试在
  Windows Proactor 下的 asyncio 传输 GC 噪音，与本仓库逻辑无关、系既有）。
  R12 新增 ~70 项：执行契约、run_script 助手、bash 守卫、write_anchor、desktop 分类、
  provider kwarg 转发、会话 outputs_dir 全生命周期（connected 帧/run.json/清退配对删/
  惰性建目录）、_FIGURE_PROMPT 文本审查
- **vitest**：60 passed（R12 新增 artifacts.ts 14 项 + protocolChat outputsDir 5 项
  + version 同源 1 项）；**tsc** / **ruff** 干净
- 无 Python 目标机的冻结语义不可真测：mock 断言 + 提示词文本审查兜底（test_orchestrator）
- **真实 UI 路径 E2E（v3.4.0，R12 断言清单全过 `[UI-E2E-R12] PASS`）**：
  Edge headless + CDP 驱动安装版（全新 APPDATA + mock SSE LLM）。
  ④ .py 文件参数启动 → 原生框自动关闭 + exit 2；① 单次点击恰 1 POST + 1 WS，
  run_python 相对 savefig 归巢 `<工作区>/outputs/<sid>/e2e_fig.png`（真实进程内
  matplotlib），connected 帧 outputs_dir 为 dock 免刷新渲染出该目录；③ dock 树行
  点击行内预览；② 折叠记忆跨页面重载保持 + 草稿行「未发送」出现；⑤ bash
  `python --version` 展开工具卡显示中文指引——cmd 报错文本与真实 Python 版本输出
  均未出现（本机有系统 Python，此反向断言排除守卫失效假绿）；磁盘 run.json
  outputs_dir/status 佐证。共四轮：第 1 轮 harness 失败（残留 mock 监听占 18999，
  请求全打到旧 mock），第 2/3 轮暴露两处断言设计问题（工具卡预览默认折叠需先展开；
  CDP 裸字符串 "1" 被二次解析成整数 1），产品代码全程零改动。
- **安装版裸协议 E2E**（v3.3.2 时做，后端未再变）：
  mock SSE 全链路回合 PASS；死端口 45s 有界报错且带中文指引；黑洞端点（TCP 通
  不响应）约 275s 有界失败（60s 首字节窗 ×4 次尝试 + 重试间隔），期间
  `/api/status` 137 次轮询零失败（事件循环全程存活）
- **真实 UI 路径 E2E**（v3.3.3，本轮新增的验证层）：
  Edge headless + CDP 驱动安装版真实 bundle → 真输入框打字、真点击发送 →
  回复上屏、run_python 工具卡「✓ 完成」、相位点 `bg-ok`（绿）、无任何报错横幅、
  单次点击恰好 1 次 POST + 1 个 WebSocket；desktop.log 完整走完
  `连接建立→回合开始→回合结束(complete, 4.7s)→断开`
- **安装包**：`dist/ResearchAssistant_setup_3.3.3.exe`（静默安装/卸载验证通过；
  build.py 泄漏扫描通过——.env 不入包）

## 6. 已知问题 / 待办

1. **用户侧确认**（最高优先）：另一台电脑覆盖安装 v3.3.3，验证会话与任务正常。
2. **密钥轮换**（用户操作）：历史上有两个 API Key 泄露进旧 git 历史，虽已做历史
   清理但必须到服务商后台吊销轮换（详见会话记录，勿写入本仓库）。
3. ~~**会话列表日期显示异常**~~ **R11 已修**：根因是后端按契约返回 epoch 秒、
   前端 `formatRelative` 把数字当毫秒（diff≈56 年落进绝对日期分支→1970-01-22）。
   修复在前端 `toMillis` 归一；协议契约（秒）未动。发版后用户侧残留的旧截图
   现象即消失。
4. ~~**空会话堆积**~~ **R11 已修（三层）**：① 后端列表前清退「零轮次且 >1h」
   目录（零轮次 ≡ 从未收到用户帧，因用户消息回合前先落盘——删之绝对安全，
   测试机上已有的 4 个空会话会在升级后首次打开列表时自动消失）；② 前端
   POST 后连接失败/帧未发出时补偿删除本次新建目录；③ 工作区切换复位会话态
   （堵住「幂等重建无标题目录」的入口）。
5. ~~**等待横幅提示环境变量**~~ **R11 已做**：横幅文案已提示
   `RA_LLM_FIRST_BYTE_TIMEOUT=30` 及其位置（%APPDATA% 全局 .env）。默认值 60s
   维持不变——给推理型模型留首字节时间是有意取舍，仅文档化不调参。
6. **仓库卫生**：`dist/` 存有 3.3.0/3.3.1/3.3.2/3.3.3 四个安装包，发版后可清理旧版；
   `D:\vscode files\research-assistant-history-backup-20260822.bundle` 含旧历史，
   确认无需回溯后删除。
7. **R12 已知边界（如实记录）**：
   - `verify_citations` 处理器以相对路径写 output_file 时不过 write_anchor（独立处理器
     路径，未走 registry 注入）——调用方需传绝对路径；
   - bash python 守卫只在冻结态生效（开发态有系统 Python，有意不拦）；`where python`
     等无害读命令有意放行；
   - 会话 dock 的 REST 列表 outputs_dir 仅恢复期兜底——工作区切换后权威源是 connected 帧；
   - 任务页 dock 展示选中运行的 `writing_outputs/<name>`，新启动的运行要等回合结束
     refreshRuns 后才会出现在历史列表并被选中。
8. **科研 OS 资源边界**：`DurableScheduler` 已提供持久化队列、租约、重试、优先级、资源
   key、预计等待时间和 provider/worker 并发限制；资源槽位争用会延迟回队且不消耗重试预算；
   `PlatformStore.resource_usage` 聚合项目、workflow 和 Agent role 的成本/token/耗时；
   `resource_leases` 已支持多进程横向 provider/model 槽位协调，项目依赖锁 hash 已进入分析
   manifest。真正的容器镜像级隔离仍属于后续增强，不影响单机科研 OS beta 主流程。

## 7. 尝试过但失败 / 踩过的坑（避免重蹈）

- **E2E 证据污染**：残留的 headless Edge 进程会在下次启动时因同 profile 复用旧
  浏览器，CDP `/json/list` 打到**陈旧标签页**（后端已死的页面），造成「假成功/假
  失败」。必须：测试前 `taskkill /F /IM msedge.exe`、用一次性 `--user-data-dir`、
  校验目标页 URL 含当前端口。
- **Git Bash 跑 Inno Setup**：`/VERYSILENT` 等开关被 MSYS 路径转换成文件路径，
  安装器弹「Select Setup Install Mode」挂死。安装/卸载一律用 PowerShell
  `Start-Process -ArgumentList "/VERYSILENT",...`。
- **GBK 控制台**：Python 脚本打印 emoji/中文到默认控制台会
  `UnicodeEncodeError`，跑 E2E 带 `PYTHONIOENCODING=utf-8`。
- **日志切片失真**：按「启动前行数」切片读 desktop.log 会因 RotatingFileHandler
  轮转错位而误报 0 命中；验证日志一律直接读文件尾部。
- **R9 看门狗第一版**：把看门狗包在整个重试循环外，超时异常绕过全部重试——被
  自己写的回归测试当场抓住后改为每尝试监督。
- **首字节窗与旧测试契约冲突**：`first_byte_timeout` 需取
  `min(heartbeat_timeout, env 值)`，否则显式传小 `heartbeat_timeout` 的旧测试失效。
- **E2E 探测脚本**：CDP `Runtime.evaluate` 的返回值可能是裸字符串（"ok"），不能
  一律当 JSON 解析；轮询终态要等相位点落到 `bg-ok`/`bg-danger`，不能见首条回复就收。
- **mock 端口残留监听**：上一轮 mock_llm 进程还活着时新 mock bind 失败（10048），
  全部请求打到旧路由逻辑——断言静默假绿/假红且极难察觉。启动前
  `netstat -ano -p TCP` 查端口 LISTENING pid 并 taskkill。
- **工具卡结果预览默认折叠**：ToolCardView 点击头部才把「结果」渲染进 DOM，
  innerText 探测前必须先展开卡片；守卫类断言还要加反向信号（cmd 报错文本、
  真实 Python 版本输出都不得出现），否则开发机上守卫失效会假绿。

**真实 UI E2E 脚本**：`C:\Users\zhangliufeng\AppData\Local\Temp\ra_ws_e2e\e2e_r10_ui.py`
（依赖：mock OpenAI SSE 服务 `mock_llm.py` 同目录 18999 端口；已装安装版；运行方式
`PYTHONIOENCODING=utf-8 python e2e_r10_ui.py`）。Temp 目录可能被系统清理，必要时
按 §7 坑位说明重写——核心断言：单次点击 → posts=1 / sockets=1 → 回复上屏 →
相位点 bg-ok → 服务端日志完整回合。

**R12 发版断言清单**（在 v3.3.3 断言之上追加）：

1. 一次真实发送 → `<工作区>/outputs/<sid>/` 落盘，右侧 dock 免手动刷新渲染出该目录；
2. dock 折叠/展开切换后页面重载记忆保持（localStorage `ra.artifacts.dock.collapsed`）；
3. 工具卡文件 chip 点击可在弹窗/dock 行内预览；
4. exe 以 .py 文件路径为参数启动 → 快速 exit 2，desktop.log 尾部含定向解释
   （读日志一律读尾不切片）；
5. 让助手跑 `python --version` → 工具卡返回中文替代路径指引而非 cmd 报错；
6. 回归：合法目录启动不受影响；任务仍产出 `writing_outputs/<ts>_<desc>/` 结构。

## 8. 下一步开发顺序

1. ~~**发 v3.4.0**~~ **已完成**：`python build.py` → ISCC → 真实 UI E2E
   `[UI-E2E-R12] PASS` → 静默装/卸/重装验证 → 泄漏扫描 → 提交推送。
2. **目标机验证 v3.4.0**：重点验 ① 无 Python 机器上让助手画图/跑脚本（应走
   run_python，工具卡不再出现「目录不存在」；bash 裸 python 应显示中文指引）；
   ② 会话产物落 `outputs/<sid>/` 且右侧 dock 免刷新出现；③ 任务页选中历史运行
   可预览 `writing_outputs/` 产物；④ 侧栏页脚显示 v3.4.0。
3. **仓库卫生**（§6.6）：清旧安装包（dist/ 现存 3.3.0~3.4.0 五个）、删备份
   bundle（密钥轮换完成后）。
4. 功能线回到主计划：按 README/既定 roadmap 继续。

---

*本文档只记录交接所需事实；运行细节与排查过程见 git log（R7~R10 提交信息）与会话记录。*


---

## 平台化改造（v3.5 进行中 · 2026-08-24）

本轮把应用从「论文生成工具」推进为科研工作平台，已落地并验证（后端 717 passed, 1 skipped / ruff clean / 前端 60 tests + build 通过）：

- **后台任务运行时**：`research_assistant/runtime/`（SQLite WAL PlatformStore + BackgroundTaskHub）。任务与 WebSocket 解耦：断连只停止观察，不取消生成；observe 协议 + seq 事件回放；孤儿任务重启标记 interrupted。REST /api/tasks*。
- **前端后台任务 UX**：任务页「后台任务」卡（running 任务列表 + 继续观察），active taskId/seq 本地持久化，重连回放错过事件。
- **性能治理**：LLM/工具逐次计时审计（llm_timing/tool_timing）；研究与图表阶段 FIRST_COMPLETED 即时推进；引用校验持久缓存（DOI/标题键、30 天 TTL、原子写）；移除规划器硬性章节数偏置。
- **产物版本化**：ArtifactVersionStore 记录 agent write/edit 前后快照，REST 列表/diff/一键恢复；设置页「变更」入口。
- **项目长期上下文**：项目指令持久化于平台库（GET/PUT /api/project/instructions），注入流水线每个子代理系统提示；设置页可视化编辑。
- **上下文一致性与恢复**：项目指令和资料检索块同时注入单代理任务；进程重启产生的 `interrupted` 任务在任务页可一键重新运行（保留查询与模式）。
- **文档**：docs/protocol.md §5.3 后台任务协议、§5.3.1 DAG、§5.3.2 脚本产物版本化。
- **工作流 DAG**：论文任务创建时持久化 `plan → {research, figures} → assemble → gates → finalize` 节点、依赖和状态；`GET /api/tasks/{id}/plan` 在断线后仍可恢复，任务页同步展示。
- **通用 Agent 工作流**：新增 `AgentRole` / `WorkflowDefinition` / `WorkflowRegistry`，保留论文专用执行器，并提供研究问题冲刺、可复现数据分析两种通用 DAG；任务页可选择工作流，节点检查点写入 `.ra/workflow/`。
- **产物版本化补齐**：`bash`/`run_python` 的间接新增、修改、删除也记录进可恢复变更历史；快照仅覆盖产物锚点并有文件数/字节上限，避免影响任务关键路径。
- **产物审阅闭环**：后台任务完成或失败后自动索引真实输出文件，写入相对路径、版本、SHA-256、
  文件类型和 Citation/Doc Gate 汇总状态；变更版本自动递增，失败门禁写入质量风险，并通过
  task → artifact provenance 关联到线程和研究运行。
- **性能可观测性**：`GET /api/tasks/{id}/metrics` 提供总耗时、DAG 关键路径、节点耗时和事件数，任务页实时显示，便于定位慢阶段；事件写入、资料库读写和检索均移出事件循环。
- **混合资料检索**：资料库新增 `keyword` / `semantic` / `hybrid` 模式和离线确定性向量，保留页码、片段、哈希锚点；任务页可切换检索模式。
- **模型分级路由**：通用 Agent 角色支持 `fast` / `strong` / `default` 分级，配置 `RA_MODEL_FAST`、`RA_MODEL_STRONG` 即可降低规划/审阅延迟，同时保留单模型兼容。

后续路线（见 docs/protocol.md 与本文件历史）：用户可配置工作流持久化、真正的模型向量服务与
跨项目知识图谱、增量质量门，以及多任务共享连接池与限流策略。

## 当前闭环状态（plan260824.md 后续实施）

- `ArtifactReviewView` 已提供文件真实预览、版本 diff、provenance/质量门禁和审阅回写；
  `/api/artifacts/reviews/{id}/request-changes` 会写线程 Agent Item 与通知。
- `AnalysisRunsView` 已支持比较、复现运行和将结果挂接主张；复现通过
  `RA_ANALYSIS_*_JSON` 环境契约执行脚本，失败进入 `quality_items`。
- `/api/project/export` / `/api/project/import` 提供研究包闭环：manifest 含研究图谱、任务、
  运行、审阅、质量和通知，workspace 文件安全打包，排除 `.env`、`.ra`、VCS 和缓存。
- 工作流节点可经 `/skip` 或 `/takeover` 人工控制并留下审计 item；审批请求具有一次性
  `request_id`，前端显示 Agent/角色，错误或迟到回执不会被下一次审批消费。

科研 OS beta 主流程已串成真实浏览器 Playwright E2E，并继续保留真实模型长任务、目标机和
多进程 worker 作为发布后的持续验收；schema diff、导入冲突策略、审批收件箱和 Agent roster
已完成并纳入自动化测试。
