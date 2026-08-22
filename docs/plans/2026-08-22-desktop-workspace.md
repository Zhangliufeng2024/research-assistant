# R5 改造计划 —— 桌面工作区（Desktop Workspace）

> 日期：2026-08-22 · 状态：已批准
> 目标范式：Claude Desktop / Codex Desktop —— **打开一个文件夹工作，对话为主界面，
> 文件是 agent 干活的可见副作用**。前一计划（frontend-redesign）交付的「墨台」控制台
> 是本计划的 UI 地基。

## 0. 结论先行

产品内核已经是通用 agentic harness（`run_agent` + 7 工具 + steer + 审批 + 预算 +
events.jsonl 镜像），被"文档生成"绑死的只有 `api.generate_paper` 一层皮。
本计划做三件事：

1. **R1 工作区化**：让 UI 看见整个工作文件夹（树浏览 + 泛化文件预览），不再只有 `writing_outputs/`；
2. **R2 会话模式**：新增 `/ws/chat` 通用循环端点 + 「会话」视图（聊天流 +
   内联工具/文件卡片 + 文件树侧栏）——对话成为主界面，"生成长文档"降级为其中一种指令；
3. **R3 桌面壳**：pywebview 原生窗口包住本地 FastAPI（零 node），进现有 PyInstaller
   打包链，产出单 exe 的 "ResearchAssistant Desktop"。

## 1. 现状盘点

**已具备（直接复用）**

| 能力 | 位置 | 在本计划中的角色 |
|---|---|---|
| 通用 agentic 循环 | `agent.run_agent(RunConfig)` | 会话模式的引擎，零改动 |
| 审批三态 + 审批卡 | kernel/approval + 前端 approvalCard | 会话内联审批，协议零改动 |
| steer 中途转向 | run_agent(steer_queue) | 会话天然就是连续 steer |
| 会话镜像 + 事件日志 | SessionStore（任意 run_dir） | 会话历史持久化载体（D2） |
| 预算硬闸门 + usage 推送 | BudgetGuard + {"type":"usage"} | 会话成本可见 |
| 路径围栏 | core.safe_resolve | 工作区文件 API 的安全底座 |
| 权限拦截 / ExecProvider seam | permissions / exec_provider | 会话工具安全 + 未来沙箱 |
| 「墨台」组件库 | static/js/components/* | 聊天流/卡片/modal/md 渲染全复用 |
| PyInstaller spec | ResearchAssistant.spec | 桌面壳打包入口 |

**缺失（本计划补齐）**
- 工作区概念：服务端绑定启动 CWD，UI 仅见 `writing_outputs/`
- 通用会话端点：无 `/ws/chat`；`generate_paper` 把循环藏在了文档流程里
- 文件树 / 泛化预览 API（现在只有 papers 结构化扫描）
- 桌面壳与选夹体验

## 2. 架构决策（D1–D5）

- **D1 双模式共存，会话为主**：「会话」是默认主视图；「任务」（现驾驶舱）保留为
  长任务/pipeline 监控视图。两者共享同一套内核预算/hook/日志；UI 上会话里可一键
  跳转驾驶舱发起 pipeline（显式按钮，不做意图魔法识别）。
- **D2 会话持久化复用 SessionStore**：每会话一个目录
  `<workdir>/.ra/sessions/<YYYYMMDD_HHMMSS_slug>/`，内含 `run.json`（mode="chat"）
  与 `events.jsonl`（msg_add 镜像已内置）。另存 `history.json`（归约后的完整
  messages 数组）供重启恢复——重放 events 重建 messages 太脆弱，直接存权威副本，
  events 仍只作审计。
- **D3 桌面壳用 pywebview**：纯 Python、零 node 工具链，符合项目基因；
  Win11 自带 WebView2 运行时。Tauri/Electron 明确不采用。
- **D4 安全基线不放宽**：会话模式工具权限与 pipeline 一致（`RA_PERMISSION_MODE`
  默认 deny_dangerous；`RA_APPROVAL_MODE` 可开 ask）；所有文件 API 过
  `safe_resolve(root)`；shell-open 类能力需 `RA_ALLOW_SHELL_OPEN=1` 显式开启。
- **D5 协议版本化**：新增 WS 端点与消息 kind 按 `docs/protocol.md` §9 承诺处理
  （只增不改；消费方容忍未知 kind）。协议文档随代码同步更新。

## 3. 分期实施

### R1 工作区化

| # | 项 | 说明 |
|---|---|---|
| W1 | `GET /api/workspace` | `{root, name, output_folder, has_git}` 工作区名片 |
| W2 | `GET /api/workspace/tree?path=&depth=1` | 目录树懒加载：单层子项 `{name,path,type,size,mtime}`；忽略 `.git/__pycache__/.ra/node_modules/隐藏文件`；`safe_resolve` 围栏，越界 403 |
| W3 | `GET /api/workspace/file?path=` | 泛化预览：文本 ≤256KB 截断返回 `{kind:"text",content,truncated}`；图片/PDF → inline 流；`.docx/.md` → `{kind:"text",...}`（docx 用 python-docx 抽段落文本）；其余 → attachment 头 |
| W4 | `POST /api/workspace/open?path=` | 资源管理器定位目录/文件（explorer / open / xdg-open）；`RA_ALLOW_SHELL_OPEN!=1` 时 403 |
| W5 | 前端「工作区」能力 | 文件树面板组件（懒加载展开）+ 预览（文本只读高亮容器、图片/PDF 复用 modal、docx 文本流）+ 面包屑路径 |

### R2 会话模式（核心工程）

| # | 项 | 说明 |
|---|---|---|
| C1 | 会话 REST | `POST /api/chat/sessions` 新建；`GET /api/chat/sessions` 列表（含 last_message 摘要/updated_at）；`GET /api/chat/sessions/{id}` 取 history.json |
| C2 | `WS /ws/chat?session=<id>` | 无 id 自动建。**client→server**：`{action:"user",text}` / `{action:"approval",id,approved}` / `{action:"steer",message}` / `{action:"stop"}`；**server→client**：`{type:"connected",session_id}` / `{type:"text",delta}`（流式增量）/ `{type:"tool_card",id,tool,arguments,status,result_preview,files[]}` / `{type:"usage",budget}` / `{type:"approval_request",…}`（沿用现有）/ `{type:"result",stop_reason,turns}` / `{type:"error",message}` |
| C3 | 会话循环 | 直调 `run_agent`：messages 从 history.json 载入→用户消息追加→循环→全程 on_text 增量推送→结束时写回 history.json + SessionStore.finish；compaction/预算/取消全部继承 RunConfig |
| C4 | tool_card 组装 | `on_tool_start` 推 `{status:"running"}` 卡片；`on_tool_use` 回填 result_preview（≤400 字符）并从参数/结果提取产物文件（write_file 的 path、run_python 结果中的 figures/*.png 等）→ `files[]` 给前端内联渲染 |
| C5 | 前端「会话」视图 | 左：会话列表（新建/删除）；中：聊天流（用户气泡右、agent 正文走 mini-md、工具卡片内联含文件缩略图、审批卡复用、底部输入框 Ctrl+Enter 发送、运行中可继续输入=排队下一条或 steer）；右：文件树 + 本次预算 |
| C6 | 前端协议层 | 新模块 `js/protocol_chat.js`（纯函数归约，node:test 覆盖）+ `js/ws_chat.js`（复用 ws.js 连接模式） |

### R3 桌面壳

| # | 项 | 说明 |
|---|---|---|
| D1 | `research_assistant/desktop.py` | pywebview 启动器：首次运行弹原生选夹对话框→在该目录起 uvicorn（随机端口）→窗口加载；托盘图标（可选，失败降级） |
| D2 | 入口与依赖 | `research-assistant-desktop` console-script；pywebview 进 `[project.optional-dependencies].desktop`；spec 文件加 hiddenimports |
| D3 | 降级路径 | 无 GUI/无 WebView2 时打印说明回退 `research-assistant` CLI/Web 模式 |
| D4 | 打包冒烟 | `build.py`/spec 增加 desktop 入口收集；headless 环境仅做 import 级检查 |

### R4 远期（明确不在本轮）
ExecProvider 容器/远程执行世界（桌面版沙箱故事）、多工作区管理器、云同步。

## 4. 测试策略

- **pytest**：tree/file 的围栏与穿越拒绝（`..`、绝对路径、符号链接逃逸）；docx/text/pdf 预览分类；chat session CRUD；`ws/chat` 用 fake LLM client 走通 user→text/tool_card/result 全链路与断线取消；tool_card 的 files 提取规则
- **node:test**：`protocol_chat.js` 归约（文本增量拼接、工具卡状态机、审批、usage、错误）
- **手动冒烟清单**：会话里让 agent 读 data/ 的 csv 并画图→文件卡片出现且可放大；审批一次允许一次拒绝；刷新页面恢复会话历史；重启服务恢复会话可续聊；desktop exe 选夹→窗口打开→同功能；驾驶舱发起 pipeline 与会话互不干扰

## 5. 执行编排与顺序

```
[当前] Agent-1(B1-B8 后端) 落地 → 主会话联调回归 → 提交（前置依赖，必须先完成）
R1  Agent-W：workspace API（新文件 web/workspace.py + routes 注册 + tests）
    主会话并行：W5 前端文件树/预览
R2  Agent-C：chat 后端（新文件 web/chat.py + api 层薄封装 + tests）
    主会话并行：C5/C6 会话前端（先按 §3 协议 mock 开发，后端落地即联调）
R3  主会话：desktop.py + spec + 打包冒烟（依赖 R1/R2 合并后的稳定面）
每期独立 commit；web/ 热点文件串行化（上一批 agent 合并后才开下一批）
```

## 6. 风险与对策

| 风险 | 对策 |
|---|---|
| 自由对话 token 失控 | BudgetGuard 硬闸门继承 + usage 实时推送 + 会话设置默认 max_cost |
| history.json 与 events.jsonl 双源不一致 | history.json 是唯一权威（运行时即它），events 仅审计——与"模型可见即已记录"不冲突（msg_add 仍逐条镜像） |
| 大文件预览拖垮服务 | 256KB 截断 + 图片/PDF 走 FileResponse 流；docx 只抽前 N 段 |
| pywebview 各平台差异 | 仅承诺 Windows 一级支持；mac/linux 尽力 + 文档说明 |
| 会话与 pipeline 心智混乱 | 导航清晰分「会话」「任务」；会话内发起长任务显式跳转 |
