# Round-2 改造计划（2026-08-22）

> 承接 2026-08-21 主计划。本轮目标：成本、安全、一致性收尾；全部改动 pytest 全绿。

## 评估结论（遗留问题）

| # | 问题 | 影响 | 本轮处理 |
|---|---|---|---|
| 1 | Anthropic 未启用 prompt caching，数百行 system prompt 每 turn 全价重算 | 成本翻倍级浪费 | ✅ P0 |
| 2 | retry 层对已分类 LLMError 二次包装（消息重复）；RUN_END 在异常路径不发；失败工具结果无 is_error 标记 | 可观测性/协议正确性 | ✅ P0 |
| 3 | bash/run_python 无权限拦截，危险命令（rm -rf /、format、mkfs…）直达 shell | 桌面分发安全暴露面 | ✅ P1 |
| 4 | OpenAI 新模型（o系/gpt-5）要求 max_completion_tokens、拒绝自定义 temperature | 兼容性 | ✅ P1 |
| 5 | `setup_claude_skills` 用 `dirs_exist_ok=True` 盲拷，用户侧 skill 副本永不更新 | bug：修了 skill 推不下去 | ✅ P1 |
| 6 | 单 agent 模式无 run.json，`resume` 只对 pipeline 生效 | 一致性 | ✅ P2 |
| 7 | ruff 56 处错误，CI lint 必红 | CI 可信度 | ✅ P2 |
| 8 | Web 前端无停止按钮/预算输入，新后端能力不可达 | 产品完整性 | ✅ P2 |

明确不做（记录）：stream_options include_usage（部分网关会拒未知字段，兼容风险>收益）、skills 知识包路由与提示词瘦身（独立大项）、launcher 授权机制重做。

## 任务序列

1. quick-wins：retry 透传 / RUN_END finally / is_error —— agent.py + retry.py + 测试
2. prompt caching：anthropic.py `_apply_cache_control`，ANTHROPIC_PROMPT_CACHE=0 关闭 —— 测试断言 body 结构
3. permissions.py：危险命令模式表 + `RA_PERMISSION_MODE`（deny_dangerous 默认）+ RunConfig.permission_policy 自动挂载 —— 测试
4. openai_compat：模型前缀分派 max_tokens vs max_completion_tokens、o系去 temperature —— 测试
5. core.setup_claude_skills → 清单式增量同步（新增/更新/删除跟踪文件，不动用户自建文件）—— 测试
6. api.generate_paper 单 agent 分支接 SessionStore(mode=single) —— 测试
7. ruff 清零（--unsafe-fixes 审查后使用 + per-file-ignores for __init__ F401）
8. web/static：停止按钮（用 connected 返回的 task_id 调 stop 端点）+ 可选预算字段

## 验收
- `pytest -q` 全绿；`ruff check research_assistant` 退出码 0
- 缓存请求体包含 cache_control；危险 bash 被 [DENIED by policy] 拒绝
- 单 agent 运行产出 run.json 且 resume 命令可列出
