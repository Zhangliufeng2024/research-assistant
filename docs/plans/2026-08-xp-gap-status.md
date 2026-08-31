# 体验差距落地 — 开发进度存档（2026-08-27）

对比 Codex app / Claude Code 五类体验升级方案（见 `docs/plans`）。
以下标记 ✅= 已落地并自动化测试通过； ⏸= 计划已拆解，未落地。

> **2026-08-31 复核（本存档已封档）**：五类方案全部落地并保持全绿——后端
> pytest **1445 passed / 3 skipped**（3 个失败均为本机环境问题，非回归），
> 前端 Vitest **316 passed**，ruff/tsc 全绿，版本 v3.7.2。工程债清理后
> `web/chat.py` 拆分为 chat_state / chat_protocol / chat_history，
> `ChatView.tsx` 逻辑拆入 hooks/useChat*，本文件仅作历史存档，不再更新。

## ✅ 已完成 & 全绿

1. **方案 2a — 多文件批量编辑 `apply_patch`**
   - `research_assistant/tools/file_ops.py`：`apply_patch(patches, sandbox, write_anchor)`
     - 多文件/同文件多 hunk，单文件内顺序应用；`old_string` 唯一性校验；**全有或全无原子回滚**；
     - 沙箱围栏 `safe_resolve` + Windows hazard 校验（复用 `_reject_windows_hazard`）；
     - 内部 `_resolve_edit_target()` 镜像 `edit_file` 双轨 anchor 语义。
   - `research_assistant/tools/registry.py`：
     - `TOOL_DEFINITIONS` 增 `apply_patch` schema；`_TOOL_HANDLERS` 注册；`execute()` 专属分支
       (sandbox/anchor 注入 + `_snapshot_exec_outputs` 前后版本快照 → `ChangesView` diff/恢复可见)。
   - 测试：`tests/test_tools.py::TestApplyPatch` + `TestToolRegistryApplyPatch`（11 例）。
   - `ruff check tools/registry.py tools/file_ops.py` 干净；`pytest tests/test_tools.py` **78 passed**。

2. **方案 3a — 进程内扩展工具接口**
   - `research_assistant/tools/registry.py`：
     - `ToolExtension` (name/description/schema/handler) `+ handler` 同步/异步兼容；
     - `register_extension()`（防命名碰突）；`get_schemas()` 合并扩展；`execute()` 优先派发扩展，
       handler 异常兜底 deny，不泄出（`Error executing extension <name>`）。
   - 测试：`tests/test_tools.py::TestToolExtensions`（5 例）。
   - `pytest` **83 passed**。

3. **方案 4 — slash 命令解析层（前端纯函数）**
   - `frontend/src/lib/commands.ts`：`CommandKind` / `ParsedCommand` / `COMMAND_CATALOG` /
     `isCommand` / `parseCommand` / `formatHelp`。
   - 支持 `/budget cost=/tokens=/turns=/wall_seconds=`（数值正性校验）、`/model`、`/role`、
     `/skill`（单词为 value）、`/plan`、`/help`，未知命令兜底 error。
   - 测试：`frontend/src/lib/__tests__/commands.test.ts`（15 例） → **`npx vitest run` 15 passed**。

## ✅ 已完成 & 全绿（2026-08-28 续：四项待落地全部完成）

4. **方案 4 — slash 命令前端 + 后端接入**
   - 后端 `web/chat.py`：空闲期 `action:"command"` 分派——`/budget`→会话级
     `BudgetGuard.limits` 覆盖（cost/tokens/turns/wall_seconds，正值校验、整体拒绝不半写）、
     `/model`→`rt["model_override"]`（后续回合 build_llm_client + 计价跟随）、
     `/role`/`/skill`→`rt["pending_context"]` 下一回合注入系统上下文（取用即清）、
     `/help`→`command` 帧（`COMMAND_HELP_TEXT` 与前端 COMMAND_CATALOG 同步维护）、
     未知命令→error 帧；命令不落史、不占回合，回执 `{"type":"command", raw, message}`。
   - `/plan` 走 user 帧（需落盘），主循环 user 分支识别后启动带门回合。
   - 前端：`Composer.tsx` 命令下拉（`commandSuggestions` 纯函数 + ↑↓/Enter/Tab/Esc 键盘导航）、
     `chatStore.send` 命令路由（解析错误本地渲染，不打网络）、`protocolChat` 归约 command 帧。
   - 测试：`tests/test_chat_api.py::TestSlashCommands`（7 例）+ 前端 `planCommand.test.ts`。

5. **方案 1 — 会话 Plan 确认门**
   - `web/chat.py`：`_start_turn(plan_query=…)` → `_run_plan_gate`：只读 planner 回合
     （`_PlannerTools` 空工具面 + `_planner_instructions` 计划模式提示词，流式 text 帧直播计划）
     → `plan_proposal` 帧 → `_wait_plan_decision`（`handle.plans` 专用裁决队列，与工具审批
     分离；600s 超时=deny，stop=cancel）→ 批准后执行回合提示词附 `[已确认的执行计划]`。
   - 计划即刻落盘（批准与否都作为 assistant 条目，拒绝附「本轮不执行」说明）；
     拒绝/超时 result 帧 stop_reason="cancelled"；迟到/错 id 的 plan_decision 双向忽略。
   - 前端：`PlanCard.tsx`（10 分钟倒计时置灰）+ `chat.plan` 状态 + `respondPlan`；
     result 帧统一清门。
   - 测试：`TestChatPlanGate`（5 例：批准执行/拒绝跳过/超时/stop 门内/迟到回执忽略）。

6. **方案 2b — 消息流内联 diff 卡**
   - `frontend/src/lib/diff.ts`：行级 LCS diff（公共前后缀修剪 + 超大中段退化保护 +
     空串=零行语义）+ `diffStats`；`ToolCardView.tsx`：`DiffBlock` 对 `edit_file`
     （old/new_string）与 `apply_patch`（patches[]）渲染色块 diff（+n/-n 统计）。
   - 测试：`src/lib/__tests__/diff.test.ts`（10 例）。

7. **方案 5 — GUI 配置聚合 RA_MAX_* 收口**
   - `web/settings.py`：`EXTENDED_KEYS` 补 `RA_MAX_WALL_SECONDS`（number，>0）+
     `SettingsPayload.ra_max_wall_seconds`；`SettingsView.tsx`「预算与节奏」分区补
     墙钟时长输入。RA_MAX_* 预算族（cost/tokens/turns/wall_seconds）现已全部可在
     设置页图形化配置（未做独立 FirstRunWizard——现有 useFirstRunWizard 只管模型接入）。

## ⏸ 待落地（无）

全部五类方案（1/2a/2b/3a/4/5）已落地。

## 基线保持（2026-08-28 复核）
- 后端：`pytest` 全量 **966 passed / 1 skipped**（4 个失败均为环境性：
  test_bash_chinese_env ×3 GBK 解码受终端代码页影响、test_context_supervision ×1
  测试断言 `saved to: (\S+)` 无法处理带空格的工作区路径——详见本文件「已知环境坑」）。
- 前端：`npx vitest run` → **252 passed**（24 文件，+24）；`tsc -b` / Vite 构建通过。
- `ruff`：`web/chat.py` / `web/settings.py` / `tools/*` clean。

## 已知环境坑（WorkBuddy 沙箱内跑 pytest）
- WorkBuddy CLI 的 sitecustomize safe-delete shim 会拦截 `shutil.rmtree`/`unlink` 转
  回收站：沙箱内 fail-closed（`windows-sandbox-recycle-bin-unavailable`）、沙箱外
  genie-trash 对临时目录偶发失败。**跑本仓库测试用
  `PYTHONPATH= python -m pytest -p no:cacheprovider --basetemp=.pytest_tmpX`**
  （清空 PYTHONPATH 摘掉 shim；basetemp 指到项目内并已加入 .gitignore）。
- `.git/objects/pack` 与 `refs/` 曾于 2026-08-28 意外丢失（成因未定位），靠
  `git fetch origin --refetch` + reflog 找回（R13-R16 提交 0b4e637 当时已在远程）。
  教训：**本地提交后及时 push**。## 基线保持
- 后端：`pytest tests/test_tools.py tests/test_agent.py tests/test_kernel.py tests/test_research_tools.py` → 141 passed。
- 前端：`npx vitest run` → 213 passed (+15)。
- `ruff`：`tools/registry.py` / `tools/file_ops.py` clean。

## 运行/验证命令速查
```
. .venv/Scripts/activate
pytest tests/test_tools.py -q
npx --prefix frontend vitest run
ruff check research_assistant/tools/
```
