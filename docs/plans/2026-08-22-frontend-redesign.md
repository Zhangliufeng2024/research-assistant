# 前端重构计划 —— 「墨台」暗色研究控制台

> 日期：2026-08-22 · 状态：已批准（用户选定：墨台方向 + 全量执行）
> 前置调研：现有前端 3 文件约 1,280 行（index.html 89 / style.css 597 / app.js 592），
> 通用蓝白配色、单体 IIFE、无模块无状态管理；后端大量能力（pipeline 阶段、steer、
> 预算快照、events.jsonl、断点续跑）在前端完全不可见。

## 0. 目标与非目标

**目标**
1. 视觉彻底重做：「墨台」暗色控制台 —— 墨蓝底 + 琥珀强调 + 等宽字体主导，
   气质参照 codex TUI / 使命控制台（"机器在为你工作"）。
2. 功能补全：阶段时间轴、实时预算、steer 中途转向、运行历史与断点续跑、
   events 审计时间线、文库搜索/画廊/预览/打包下载、设置页、WS 重连。
3. 工程化：单体 JS 拆分为 ES Modules + 轻量 store；核心逻辑可用 node:test 测试。

**非目标**
- 不引入任何 node 构建链 / 前端框架（项目基因 "No SDK dependencies" +
  PyInstaller 打包链必须保持零 node 依赖）。
- 不做多语言切换（文案集中到 `js/i18n.js` 但只出中文，为未来留口）。
- 不做多用户/鉴权（本产品定位单机单用户）。
- 刷新后重新"接管"他人连接发起的运行中任务（只读监控可以，控制权不跨连接）。

## 1. 技术路线

零构建原生 ES Modules。`<script type="module" src="js/main.js">`，
浏览器原生 import，无打包器。状态管理用 ~40 行手写 store（subscribe/emit）。
模块边界按"未来可平移到框架"的组件粒度划分。

**字体策略**（离线产品，禁用 CDN）：打包 OFL 开源字体 woff2 入库
`static/fonts/`——display 用 Chakra Petch（科技控制台感，仅拉丁字符集），
数据/日志用 JetBrains Mono；中文回退系统栈（PingFang SC / Microsoft YaHei）。

## 2. 设计 Token（style.css 重写的基础）

```
背景三阶   --bg0 #0B0F14 (页面)  --bg1 #10161D (面板)  --bg2 #161E27 (浮起)
边框两阶   --line #1F2A36        --line-strong #2C3A4A
文本三阶   --fg #E6EDF3  --fg2 #8B98A9  --fg3 #55606E
强调色     --amber #E8A33D (主 CTA/进行中)   --amber-dim rgba(232,163,61,.12)
语义色     --ok #3FB68B (通过)  --err #E5534B (失败/拒绝)  --info #58A6FF (链接)
           --warn #D9A62E  --run #E8A33D (运行中呼吸点)
字体       --display "Chakra Petch" + 中文回退
           --mono "JetBrains Mono" / Cascadia Code / Consolas
           --sans 系统栈（正文）
半径       --r 4px（克制，控制台不用大圆角）
网格       8px 基准；顶栏 48px；左栏 248px；右栏 288px
动效       阶段完成 tick 弹入、运行点呼吸、页面加载 stagger、日志行淡入
           （全部 CSS-only，尊重 prefers-reduced-motion）
```

## 3. 信息架构

```
顶栏  ▙ RA·CONSOLE │ 任务 · 文库 · 设置 │ ● 模型名 (hash 路由 #/task #/papers #/settings)

任务视图（三栏驾驶舱）
├─ 左栏 248px：＋新建任务入口 · 运行历史列表（GET /api/runs：●运行中/✓完成/✗失败/⊘取消）
├─ 中央 flex：阶段时间轴（plan→research→figures→assemble→gates→revision→finalize）
│              活动流（progress 日志 + LLM text 折叠流 + 工具事件 + 内联审批卡）
│              steer 输入条（运行中可注入指令，Ctrl+Enter 发送）
└─ 右栏 288px：预算仪表（$ / tokens / turns / wall-clock，实时）· 产物列表 · 本次元数据

文库视图（双栏）
├─ 左 320px：搜索框 + 排序（日期/字数）+ 文档卡列表
└─ 右 flex：Tab（概览 │ 文件 │ 图表画廊 │ 进度日志）+ 打包下载 zip + 删除

设置视图：系统信息卡（模型/provider/API host/审批模式/RA_* 生效值/版本）只读
```

## 4. 后端配套改动（全部向后兼容，旧字段不动）

| # | 端点/改动 | 说明 |
|---|---|---|
| B1 | `GET /api/runs` | 扫描 `writing_outputs/*/run.json`，与 paper summary 合并：`{name,query,mode,status,stage,stages,budget,created_at,updated_at}`；无 run.json 的旧目录标 `status:"legacy"` |
| B2 | `GET /api/runs/{name}/events?after=N` | events.jsonl 增量尾读（`after`=已收行数），返回 `{total, events:[{ts,kind,data}]}` |
| B3 | `POST /api/runs/{name}/resume` | 读 run.json 的 query/mode，`generate_paper(query, output_dir=<run>, multi_agent=True)` 断点续跑；复用 ws 通道（ws start 消息新增 `resume_run` 字段，避免第二条并发生成通道） |
| B4 | ws `_pump` 增加 `{"action":"steer"}` | 投递到 steer_queue；`generate_paper` 新增 `steer_queue` 参数透传至 `run_agent`（single）与 `_run_stage_agent`（pipeline，经 RunConfig 或 kwarg） |
| B5 | 运行中预算推送 | single：`on_turn_start` 处 yield `{"type":"usage", budget:{...snapshot}}`；pipeline：每阶段结束 yield 同格式 |
| B6 | `GET /api/papers/{name}/export` | zipfile（标准库）流式打包整个 paper 目录 → `.zip` 下载 |
| B7 | `GET /api/status` 增强 | 追加 `provider, base_url_host(脱敏), approval_mode, permission_mode, repeat_limit, pipeline, version, python` |
| B8 | 测试 | `tests/test_web_api.py`（runs/events/resume/export/status）+ ws steer 用例 |

## 5. 前端文件结构（最终态）

```
static/
├── index.html            重写：三视图骨架 + 字体预加载
├── style.css             重写：token 系统 + 组件类（约 1,200 行）
├── favicon.svg           琥珀 ▙ 标识
├── fonts/*.woff2         Chakra Petch (600/700) + JetBrains Mono (400/700)
└── js/
    ├── main.js           入口：路由挂载、全局事件、启动恢复
    ├── store.js          createStore(initial) → {get,set,subscribe}
    ├── router.js         hash 路由（#/task #/papers #/settings #/run/<name>）
    ├── ws.js              WS 客户端：自动重连(指数退避)、消息分发、待审队列
    ├── api.js             REST fetch 封装（超时/错误归一）
    ├── protocol.js        服务端消息 → 状态归约的纯函数（node:test 覆盖）
    ├── format.js          esc/时间/字节/相对时间/basename
    ├── md.js              迷你 markdown 渲染（标题/列表/代码/粗体/链接，60 行内）
    ├── i18n.js            中文文案集中
    ├── components/
    │   ├── timeline.js    阶段时间轴（含并行 N/M 子进度、revision 轮次）
    │   ├── activity.js    活动流（日志/text 折叠/工具行/内联审批卡）
    │   ├── budget.js      预算仪表（环形/条形 + 数字滚动）
    │   ├── approval.js    审批卡（120s 倒计时环）
    │   ├── toast.js       toast 通知（替代 alert）
    │   └── modal.js       图片/pdf 预览遮罩
    └── views/
        ├── task.js        驾驶舱组装（左中右三栏）
        ├── papers.js      文库（搜索/排序/Tab 详情/画廊）
        └── settings.js    系统信息
```

## 6. 实施分期

| Phase | 内容 | 交付判据 |
|---|---|---|
| **P1 设计系统+骨架** | token 化 style.css、index.html 新骨架、js/ 目录与 store/router/ws/api 骨架、favicon、字体入库 | 页面以新皮肤渲染两旧视图，功能等价 |
| **P2 任务驾驶舱** | 阶段时间轴、活动流（含 text 不再丢弃）、预算仪表、steer 输入条、审批卡倒计时、停止/断线重连横幅 | 依赖 B4/B5；运行一次真实生成可见全链路 |
| **P3 运行历史+文库** | 左栏运行历史（B1）、resume 按钮（B3）、events 审计时间线（B2）、文库搜索/排序/画廊/进度日志渲染/zip 导出（B6） | 旧 run 可从 Web 续跑；文库可搜索可打包 |
| **P4 打磨** | 设置页（B7）、响应式折叠、a11y（aria/焦点/键盘）、空态/骨架屏、动效、toast 全量替换 alert/confirm | 手动冒烟清单全绿 |
| **回归** | pytest 全量、node --check、node:test 协议测试、手动冒烟 | 455+ 测试不红；新端点全绿 |

**执行编排**：Agent-1（后台）负责 B1–B8 后端全部（独占 `routes.py/ws.py/api.py/tests`）；
主会话负责前端全部（独占 `static/`），P2 前端按协议先对接 mock 消息，B4/B5 合入后联调。

## 7. 测试策略

- 后端：pytest 新端点（TestClient）+ ws steer；现有 455 测试不回退。
- 前端：`protocol.js`/`format.js`/`md.js` 为纯函数，`tests/js/*.test.mjs` 用
  `node:test` 运行（`npm test` 不存在，直接 `node --test tests/js/`）；
  全部 JS 过 `node --check`。
- 手动冒烟清单（写入计划执行记录）：生成一次真实文档走完 P2 全链路；
  中途 steer 一次；审批一次允许一次拒绝；刷新页面重连；resume 一次中断 run；
  文库搜索/画廊/zip；移动端宽度折叠。

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| 字体文件下载失败（网络） | 回退系统等宽/黑体栈，token 结构不变；字体属增强非依赖 |
| pipeline 的 progress stage 粒度不足以驱动时间轴 | 前端按 stage+details 归约；必要时 runner 增发细分 progress（不改协议已有字段，只新增 details 键） |
| steer 在 pipeline 模式的落点 | steer 队列注入当前活动子代理；实现于 `_run_stage_agent` 透传，行为与 CLI 一致 |
| 旧目录无 run.json | `/api/runs` 标 legacy，前端隐藏 resume 只展示文库链接 |
