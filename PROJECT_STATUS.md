# PROJECT_STATUS — 研究助手 (research-assistant-v3)

> 交接文档 · 更新于 2026-08-23 · 当前版本 **v3.3.3**（commit `18e7aa4`，已推送 origin/main）

---

## 1. 当前目标

桌面端 AI 研究助手（PyInstaller + WebView2 单机应用，FastAPI 后端 + React 前端）。
近期主线：**修复用户在第二台电脑上「会话永久思考中 / 无法建立与服务端的连接」的致命故障**。
该故障已根因修复并发布 v3.3.3；待用户在目标机器上安装确认。

## 2. 已完成内容（R6 → R10）

| 轮次 | 版本 | 内容 |
|---|---|---|
| R6 | 3.2.x | 设置页图形化模型配置 |
| R7 | 3.3.0 | React 18 前端重写 + pywebview 桌面壳（旧 ws.js 移植为 lib/ws.ts，**此处引入本轮根因**） |
| R8 | 3.3.1 | 全局配置迁移 `%APPDATA%/ResearchAssistant/.env`、免选夹直入、配置即生效 |
| R9 | 3.3.2 | LLM 调用监督体系化（两阶段看门狗/墙钟/可打断）、前端失败如实上报、等待横幅、结构化会话日志 |
| R10 | 3.3.3 | **定位并修复真正根因**：ws.ts 从未把 socket 登记进 `socks` 表；新增真实 UI 路径 E2E |

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

## 4. 修改过的核心文件

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

- **pytest**：583 passed / 1 skipped（R9 时点；R10 未动后端逻辑，仅版本号）
- **vitest**：30 passed（含 ws.ts 6 项新回归）；**tsc** / **ruff** 干净
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
3. **会话列表日期显示异常**：截图观察到列表项显示「1月22日」（当天实为 8-23），
   疑似 SessionList/summary 日期解析 bug，未排查——下一步可从
   `frontend/src/components/chat/SessionList.tsx` 与后端 sessions 列表接口查起。
4. **空会话堆积**：前端「先 POST 建会话目录、再连 WS」的时序下，创建后回合从未
   开始的「未命名会话」会留在列表（测试机上已见 4 个）。可考虑：首回合成功才建
   目录，或列表 GC 零轮次会话。
5. **黑洞端点默认失败耗时 ~275s**：有界但偏长（设计取舍：给推理型模型留首字节
   时间）。用户可用 `RA_LLM_FIRST_BYTE_TIMEOUT` 调低；也可考虑在等待横幅文案中
   提示该环境变量。
6. **仓库卫生**：`dist/` 存有 3.3.0/3.3.1/3.3.2/3.3.3 四个安装包，发版后可清理旧版；
   `D:\vscode files\research-assistant-history-backup-20260822.bundle` 含旧历史，
   确认无需回溯后删除。

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

**真实 UI E2E 脚本**：`C:\Users\zhangliufeng\AppData\Local\Temp\ra_ws_e2e\e2e_r10_ui.py`
（依赖：mock OpenAI SSE 服务 `mock_llm.py` 同目录 18999 端口；已装安装版；运行方式
`PYTHONIOENCODING=utf-8 python e2e_r10_ui.py`）。Temp 目录可能被系统清理，必要时
按 §7 坑位说明重写——核心断言：单次点击 → posts=1 / sockets=1 → 回复上屏 →
相位点 bg-ok → 服务端日志完整回合。

## 8. 下一步开发顺序

1. **等用户确认 v3.3.3 在目标机器正常**（若仍有问题，取该机
   `<工作区>/.ra/logs/desktop.log`，R9 的结构化日志已能区分「WS 未达」与「回合失败」）。
2. **修会话列表日期显示**（§6.3，小改动）。
3. **空会话治理**（§6.4）：建目录时机后移或零轮次 GC。
4. **等待体验打磨**（§6.5）：横幅文案提示 `RA_LLM_FIRST_BYTE_TIMEOUT`；评估默认值。
5. **仓库卫生**（§6.6）：清旧安装包、删备份 bundle（密钥轮换完成后）。
6. 功能线回到主计划：按 README/既定 roadmap 继续（R11+ 待定）。

---

*本文档只记录交接所需事实；运行细节与排查过程见 git log（R7~R10 提交信息）与会话记录。*
