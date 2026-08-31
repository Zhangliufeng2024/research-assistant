# Research Assistant v3 质量评估报告

> 评估日期：2026-08-31  
> 评估范围：完整代码库（后端 Python + 前端 TypeScript + 测试 + 文档）

> [!IMPORTANT]
> **本文由第三方（Agnes/Sapiens AI）生成，指标数字已过时，仅供历史参考。**
> 2026-08-31 工程债清理（统一重复实现 / 拆分巨型文件 / 性能热点 / DB 保留期）
> 完成后实测基线：后端 **22,457 行 / 91 个源文件**，前端 **15,313 行 TS/TSX**，
> 测试 **16,139 行 / 70 个 pytest 文件**；pytest **1445 passed / 3 skipped**
> （3 个失败均为本机环境问题：GBK 控制台 ×2、.env 残留 provider 干扰 ×1，
> 清空环境后全过），前端 Vitest **316 passed**，ruff/tsc 全绿，版本 **v3.7.2**。
> 文中"测试 19,778 行 / 71 个文件""后端 25,695 行 / 82 个文件"等数字一律以
> 上表为准；3.6.0 代码评审（docs/CODE_REVIEW_2026-08-31.md）列出的 S1–S9
> 严重问题已在 3.7.0 修复并在当前代码复核确认。

---

## 一、项目概览

| 维度 | 指标 |
|------|------|
| **后端代码** | ~22,457 行 Python（91 个源文件） |
| **前端代码** | ~15,313 行 TypeScript/TSX |
| **测试代码** | ~16,139 行 Python + 70 个测试文件 |
| **提交历史** | 65 次提交（2026.7-8 高频迭代） |
| **CI/CD** | GitHub Actions 全链路（lint + test + build） |
| **当前版本** | v3.7.2 |
| **架构模式** | FastAPI + React 18 + WebView2 桌面壳 |

> 工程债清理后的模块布局：`runtime/platform_store.py` 已按域拆为
> `store_base/store_tasks/store_research/store_queue`；`web/chat.py` 拆出
> `chat_state`（状态/历史 IO）、`chat_protocol`（纯函数层）、`chat_history`
> （历史治理 REST）；`ChatView.tsx` 逻辑拆入 `hooks/useChat*`。

---

## 二、多维度质量评估

### 2.1 架构设计（A级）

**亮点：**
1. **三层架构清晰**：宿主层（IO）→ Pipeline层（状态机）→ Kernel层（循环+钩子）
2. **状态机驱动**：`PLAN → RESEARCH∥ → FIGURES∥ → ASSEMBLE → GATES → REVISION → FINALIZE`
3. **Hook 系统**：生命周期事件总线，支持 `PRE_TOOL_USE` 拦截、审批、权限策略
4. **MCP 集成**：Model Context Protocol 客户端，支持 stdio 子进程接入
5. **双轨文件制**：会话产物 `outputs/<sid>/` + 任务产物 `writing_outputs/`

**可改进点：**
- Pipeline 与 Kernel 的职责边界偶有模糊（`orchestrator.py` 与 `agent.py` 有重叠）
- 缺少显式的插件系统（目前是硬编码工具注册）

---

### 2.2 代码质量（A级）

**度量指标：**
- 异步代码覆盖率：41/82 文件使用 async/await（50%）
- 异常处理：核心路径均有 try-except 防护
- 日志记录：15/82 文件有 logging 输出（偏少）
- 代码规范：ruff lint 全绿，line-length=100

**文档质量：**
- `docs/protocol.md`：协议规格详细（参照 OpenAI Codex 风格）
- `CLAUDE.md`：系统提示词完整（领域检测、引用政策、完成信号）
- `README.md`：功能清单详尽，架构说明清晰
- `PROJECT_STATUS.md`：版本迭代记录完整

**潜在问题：**
- 部分核心文件过大：`chat.py` (2574行)、`platform_store.py` (2014行)、`routes.py` (1965行)
- TODO/FIXME 标记仅 3 个文件（质量好，但需确认无遗漏）

---

### 2.3 测试覆盖（B+级）

**测试架构：**
- pytest 框架，71 个测试文件
- vitest 前端测试，37 个测试文件
- 真实浏览器 E2E 测试（Playwright/CDP）
- Eval harness：golden tasks + 离线指标计算

**优势：**
- 关键缺陷有回归测试（如 ws.ts socket 登记缺失）
- 性能基准测试（`perf_research_os.py`）
- E2E 验证真实 UI 路径（非 mock）

**不足：**
- 覆盖率未公开（CI 只报告不阻断）
- 缺少 property-based testing
- 前端组件测试深度有限

---

### 2.4 安全设计（A级）

**安全措施：**
1. **工作区围栏**：`safe_resolve()` 强制路径在项目目录内
2. **Windows 危险路径拒绝**：NTFS 备用数据流、保留设备名拦截
3. **执行契约四层防御**（R12）：
   - 提示层：冻结态禁裸 python
   - bash 拦截层：逐段检查 python/pip 调用
   - frozen_exec：子进程注入 run_script/WS
   - desktop 入口：文件参数 exit 2 + 定向文案
4. **MCP 环境变量隔离**：子进程无 API key

**风险点：**
- bash/run_python 工具仅验证 cwd，不检查命令内容（设计如此，依赖外层限制）
- 容器级隔离为"后续增强"，当前仍为进程级

---

### 2.5 可靠性工程（A级）

**韧性设计：**
1. **两层看门狗**：首字节窗口 + 静默心跳 + 墙钟兜底
2. **预算硬闸门**：token/$/轮数/时长任一超限即优雅停机
3. **状态持久化**：`history.json` 权威写回，断线重连续播
4. **孤儿任务清理**：宽限到期协作停止 + 硬取消兜底
5. **幽灵会话墓碑**：删除后写回拦截，防止重建

**监控能力：**
- events.jsonl 审计日志
- LLM/tool 逐次计时
- BudgetGuard snapshot 实时用量

---

### 2.6 用户体验（B级）

**优势：**
- Claude 式现代界面（深/浅双主题）
- 实时流式输出 + 工具卡 + 审批卡
- 全局 Ctrl+K 命令面板
- 右侧产出 dock（懒加载树 + 行内预览）

**不足：**
- 首次运行向导较简（仅配置 API key）
- 缺少 onboarding 引导流程
- 移动端适配未考虑（WebView2 固定窗口）

---

## 三、与 WorkBuddy/Codex/Claude Cowork 的差距分析

### 3.1 通用能力差距

| 能力维度 | Research Assistant | WorkBuddy/Codex/Claude | 差距等级 |
|----------|-------------------|------------------------|----------|
| **文件系统访问** | 工作区围栏内 | 全域（Desktop/Downloads/Documents） | ⚠️ 显著 |
| **浏览器自动化** | 无 | 内置 agent-browser skill | 🔴 缺失 |
| **记忆系统** | 无（会话级） | 三层记忆（云/本地/工作区） | 🔴 缺失 |
| **多模态交互** | 图片生成（NIM/OpenAI） | 文本/图片/视频/3D | 🟡 中等 |
| **插件生态** | MCP stdio | MCP + Skills + Connectors | 🟡 中等 |
| **多会话管理** | 基础 | 会话组/搜索/归档 | 🟡 中等 |

### 3.2 技术架构差距

**WorkBuddy/Codex 优势：**
1. **Skill 系统**：可安装/卸载的技能包（find-skills、marketplace）
2. **Connector 生态**：外部服务授权（GitHub、Notion、Figma 等）
3. **Expert Center**：专家角色切换（100+ 领域专家）
4. **跨项目记忆**：MEMORY.md 持久化用户偏好
5. **多协议支持**：HTTP/SSE/WebSocket 统一抽象

**Research Assistant 特点：**
1. **科研垂直深度**：论文生成流水线、引文验证、质量门禁
2. **状态机编排**：多阶段 DAG 执行（plan → research → figures → assemble）
3. **产物可追溯**：SHA-256 + 版本 diff + 一键恢复
4. **目标机友好**：PyInstaller 打包，无 Python 环境也可运行

### 3.3 具体功能差距

#### 3.3.1 浏览器操作
- **WorkBuddy**：`agent-browser` skill 支持打开网页、截图、点击、表单填写
- **Research Assistant**：无原生浏览器能力，需依赖外部工具

#### 3.3.2 记忆与上下文
- **WorkBuddy**：三层记忆（云记忆/本地 MEMORY.md/工作区 memory）
- **Research Assistant**：无持久化用户记忆，每次会话独立

#### 3.3.3 文件操作
- **WorkBuddy**：读取任意本地文件、PDF、图像、视频
- **Research Assistant**：工作区内文件读写，有安全围栏

#### 3.3.4 工具扩展
- **WorkBuddy**：Skills 市场 + MCP 服务器 + Connector 插件
- **Research Assistant**：内置工具 + MCP stdio 客户端（功能更简单）

#### 3.3.5 多智能体
- **WorkBuddy**：Expert Center 多专家协作
- **Research Assistant**：多代理流水线（Planner → Research ×N → Figures ×M → Assembly → Review）

---

## 四、综合评价

### 4.1 项目定位

Research Assistant 是一个**科研垂直领域的 AI 助手**，而非通用 AI 办公助手。其核心价值在于：

1. **论文生成流水线**：从研究到发表的全自动化的 IMRaD 结构生成
2. **引文真实性保证**：CitationGate 强制验证，零容忍虚构引用
3. **产物版本控制**：变更记录 + 一键恢复
4. **目标机友好**：PyInstaller 打包，无 Python 环境也能运行

### 4.2 工程化水平

| 维度 | 评级 | 说明 |
|------|------|------|
| 架构设计 | A | 清晰分层，职责分明 |
| 代码质量 | A | ruff 全绿，类型注解完整 |
| 测试覆盖 | B+ | 关键路径有回归测试，覆盖率待提升 |
| 安全设计 | A | 围栏 + 契约 + 审计三重防护 |
| 可靠性 | A | 看门狗 + 预算闸门 + 持久化 |
| 用户体验 | B | 功能完整，交互细节待打磨 |

### 4.3 与顶级产品的差距本质

Research Assistant 与 WorkBuddy/Codex/Claude 的差距**不在代码质量**（已达 A 级），而在于：

1. **产品定位差异**：垂直科研 vs 通用办公
2. **生态建设滞后**：Skill/Connector/Expert 体系未建立
3. **记忆系统缺失**：无跨会话用户偏好学习
4. **多模态能力有限**：仅图片生成，无视频/3D
5. **浏览器自动化空白**：无法操作网页/表单/截图

### 4.4 建议改进优先级

**P0（核心缺失）：**
1. 引入三层记忆系统（云/本地/工作区）
2. 集成 agent-browser skill（Playwright/CDP）
3. 建立 Skill 市场机制（可安装/卸载）

**P1（体验提升）：**
1. 首次运行向导增强（场景选择、能力介绍）
2. 多会话管理优化（分组/搜索/归档）
3. 移动端响应式适配

**P2（生态扩展）：**
1. Expert Center（领域专家角色）
2. Connector 插件（GitHub/Notion/Figma）
3. 多模态生成（视频/3D）

---

## 五、结论

Research Assistant v3 是一个**工程化质量卓越、领域深度独特**的科研 AI 助手。其代码架构、可靠性设计、安全机制均达到 A 级水平，在论文生成流水线、引文验证、状态持久化等方面具有不可替代的价值。

与 WorkBuddy/Codex/Claude 的差距本质是**产品定位差异**而非技术能力差距。若目标是成为通用 AI 办公助手，需补强记忆系统、浏览器自动化、Skill 生态；若坚持科研垂直定位，则应在论文质量门禁、领域知识库、期刊模板等方面继续深化。

---

*报告生成：Agnes (Sapiens AI)*  
*评估时间：2026-08-31*
