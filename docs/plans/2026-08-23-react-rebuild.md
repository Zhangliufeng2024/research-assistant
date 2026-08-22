# R7 计划：React 全家桶前端重建（Claude 式现代风）

日期：2026-08-23 ｜ 前置：R6（安装程序+图形化设置）已发布 v3.2.0

## 背景与决策

用户试用 v3.2.0 安装包后认为前端质量不足，对标对象是 Claude Desktop。
诊断：渲染壳无差距（WebView2 与 Electron 同为 Chromium），差距在前端应用层——
vanilla 手搓 DOM 无组件框架、Markdown 简化实现、极客风视觉错位。

| # | 决策 | 说明 |
|---|------|------|
| D1 | React 18 + TypeScript + Vite + Tailwind v4 + framer-motion | 用户选定「React 全家桶」 |
| D2 | 视觉走 Claude 式现代风：浅/深双主题、暖中性底、赤陶强调色、圆角卡片、大留白 | 用户选定；替代「墨台」控制台风 |
| D3 | 源码在 `frontend/`；`vite build` 直出 `research_assistant/web/static/`（替换旧 vanilla 全部） | 单一产物目录，PyInstaller 打包链不变 |
| D4 | 构建产物入库提交 | 打包机无需 node（本机有 Node 24，但保持 build.py 零 node 依赖） |
| D5 | 后端零改动：REST/WS 协议、pywebview 壳原样保留 | 归约逻辑从 protocol_chat.js 忠实移植到 zustand store |
| D6 | WS 语义不变：task/chat 双通道、chat 断连不自动重连（服务端取消语义）、generate start 驱动握手 | 见 docs/protocol.md §5/§10 |
| D7 | Markdown：react-markdown + remark-gfm + remark-math/katex + rehype-highlight | 学术产物需要公式与表格 |
| D8 | 字体自托管：@fontsource（Inter 可变字重 + JetBrains Mono），不依赖任何 CDN | 中国网络环境 |
| D9 | 测试：vitest 覆盖 store 归约与关键组件；scripts/smoke_live.py 标记随新 DOM 更新 | |
| D10 | **窗口化构建（console=False）**：安装版不再弹出黑色 cmd 窗口；日志改写文件（工作区 `.ra/logs/`）；服务器启动失败/WebView2 缺失用 GUI 弹窗提示而非静默退出 | 用户明确要求「正式桌面安装包」体验 |
| D11 | **单一入口承诺**：点击图标 = 只出现一个原生窗口，绝不打开浏览器；构建体系收敛到 build.py 一条路径（spec 由其生成） | 用户明确要求 |
| D12 | WebView2 运行时检测：缺失时 tkinter 弹窗给下载指引（Win11 自带，Win10 需兜底） | 配合 D10 的窗口化静默失败问题 |
| D13 | **桌面图标**：PIL 矢量式绘制（scripts/make_icon.py）——赤陶渐变圆角方块+米白文档+黏土色星芒，与前端视觉同源；产物 packaging/app_icon.ico 多分辨率，接线 build.py --icon、installer.iss SetupIconFile、Web favicon 同款 SVG | 用户要求「设计好看的桌面图标」；程序化绘制保证任意缩放清晰 |

## 交付物

1. `frontend/` 完整工程（P0）＋核心库（P1）＋四大视图 Chat/Task/Papers/Settings（P2-P4）
2. `research_assistant/web/static/` 为构建产物；旧 js/css 删除
3. smoke_live.py 标记更新；pytest/vitest/ruff 全绿；真实对话往返探针
4. 版本 3.3.0（集成验证通过后发布）

## 明确不做（本轮）

- 不改后端 API/协议；不换 Tauri/Electron 壳；不做 i18n 框架；不做移动端适配
- 旧 vanilla 前端不保留兼容层（一次性切换）

## 交付记录（2026-08-22 全部落地）

- D1-D9：frontend/ 工程 + 四视图 + vitest 20 用例；`vite build` 直出 static/；
  smoke_live.py 32/32 PASS（含真实 LLM 对话往返与 generate 取消路径）
- D10-D12：desktop.py 重写为冻结入口——文件日志 `.ra/logs/desktop.log`、
  GUI 错误框、WebView2 注册表检测 + 下载指引、工作区记忆
  （%APPDATA%/ResearchAssistant/desktop.json）、v3.2.0 config.json → 工作区
  .env 一次性迁移；build.py 默认 --noconsole（--debug-console 保留调试口），
  入口收敛 launcher_desktop.py，删除手工 spec
- D13：packaging/app_icon.ico（16-256px 多分辨率）
- 版本统一 3.3.0（pyproject / `__init__` / installer.iss / 前端底栏；
  `/api/status` 改以包内 `__version__` 为准，避免构建机残留 dist-metadata）
- 验证：pytest 553 passed；ruff 全绿（`.claude/` 已排除）；dist exe 与
  setup.exe（44.9MB）均实测：静默安装 → 记忆工作区直启 → 技能同步 →
  服务就绪 → UI v3.3.0，卸载干净

## R8 交付记录（2026-08-22，v3.3.1）

用户实测 v3.3.0 反馈四项，全部修复：

1. **免选夹启动**（反馈 #1）：desktop.py 启动不再弹选夹——CLI 参数 > 上次
   记忆 > 默认目录（文档/研究助手，自动创建）。换目录改为界面内操作：
   会话页输入框下方「工作目录」入口 → 原生选夹（pywebview js_api
   DesktopBridge）或手动输路径 → POST /api/workspace/root 运行时切换
   （os.chdir + 技能重同步 + 配置重载 + app.state 刷新；生成任务运行中 409）。
2. **设置保存即刷新**（反馈 #2）：/api/status 改为实时 resolve_model；
   SettingsView save() 成功后重拉 /api/status；POST /api/settings 同步刷新
   app.state.model。
3. **配置真正生效**（反馈 #3）：ws_chat 的 LLM 客户端改为**每轮实时构建**
   （原为连接期一次，保存的新 Key/模型对已开会话永不生效）；错误帧在
   ChatView 以横幅可见（原来完全吞掉，表现为"无任何反应"）。
4. **会话 cowork 化**（反馈 #4）：系统提示强化执行原则与交付物规范
   （writing_outputs/ 落盘、图表 PNG、回合末「交付物」清单）；build.py 不再
   排除 numpy/pandas/matplotlib/PIL；run_python 冻结版改为 spawn 子进程
   执行器（tools/frozen_exec.py，freeze_support 引导、超时强杀）——线程方案
   会偷 GIL 且杀不掉，已废弃。任务面板架构未动。

配套改造：模型配置上移全局 %APPDATA%/ResearchAssistant/.env（切换工作目录
不丢；工作区 .env 降级为覆盖层；v3.3.0 工作区配置与 v3.2.0 config.json 两条
一次性迁移并存）。

验证：pytest 575 passed（新增 workspace-switch / config-global / frozen-exec /
settings env_file 用例）；vitest 20/20；tsc/ruff 全绿；live smoke 实测
status→settings 保存即生效→workspace/root 切换链。
