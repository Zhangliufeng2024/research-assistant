"""Model registry：窗口与价格数据的**单一来源**（P2-5 收敛）。

背景：窗口表（context.py）与价格表（budget.py）此前各自维护一份模型前缀
清单，且**匹配语义不同**（窗口 first-match / 价格 longest-prefix）。后果：
``gpt-4.1`` 有窗口条目（1M）却没有价格条目 → ``price_for("gpt-4.1")`` 落到
零价默认 → 成本恒为 0，``BudgetGuard.cost_cap_enforceable`` 静默退化为
False——成本上限形同虚设。

本模块只承载**数据**，不承载匹配语义：

- ``MODEL_WINDOWS``：有序元组，窗口查询保持 first-match（更具体的前缀排
  在前面），见 ``kernel.context.window_for``；
- ``PRICES_USD_PER_MTOK``：字典，价格查询保持 longest-prefix，见
  ``kernel.budget.price_for``。

新增/核实模型时**只改这里**，两张表的覆盖一致性由
``tests::test_model_registry_consistency`` 锁定。
"""

# ---------------------------------------------------------------------------
# 上下文窗口（输入 token 口径）
#
# ⚠️ window_for() 是**首个匹配即返回**（first-match），不是最长前缀匹配。
# 因此更具体的前缀必须排在更前面，否则会被宽泛条目先截走。
#
# 2026-08 核实：Fable 5 / Opus 5 / Sonnet 5 的窗口为 **1,000,000**（默认即
# 最大值，无 beta header、无长上下文附加费）；Haiku 4.5 为 200,000。
# 此前把整个 claude-sonnet / claude-opus 族写成 200_000，导致 1M 窗口的模型
# 在 140k（0.7 × 200k）就触发压缩，**浪费 86% 可用窗口**。
#
# 版本号条目在前、家族兜底在后；未知的 Claude 模型仍落到保守的族级值。
MODEL_WINDOWS: tuple[tuple[str, int], ...] = (
    ("claude-fable-5", 1_000_000),
    ("claude-opus-5", 1_000_000),
    ("claude-sonnet-5", 1_000_000),
    ("claude-mythos-5", 1_000_000),
    ("claude-opus-4", 200_000),
    ("claude-sonnet-4", 200_000),
    ("claude-haiku-4", 200_000),
    ("claude-opus", 200_000),
    ("claude-sonnet", 200_000),
    ("claude-haiku", 200_000),
    ("claude-", 200_000),
    ("gpt-5", 272_000),
    ("gpt-4.1", 1_000_000),
    ("gpt-4o", 128_000),
    ("gpt-4", 128_000),
    ("deepseek-reasoner", 128_000),
    ("deepseek-chat", 128_000),
    ("qwen", 128_000),
)

DEFAULT_CONTEXT_WINDOW = 128_000

# ---------------------------------------------------------------------------
# 价格（USD per million tokens）
#   {"input": x, "output": y, "cache_write": z, "cache_read": w}
#
# price_for() 取**最长前缀**匹配，版本级条目自然优先于家族兜底条目。
#
# 2026-08-28 核实（此前 opus 一栏 3 倍高估、fable 完全缺失）：
#   Fable 5   $10 / $50    Opus 5  $5 / $25    Sonnet 5  $2 / $10（intro）
#   Haiku 4.5  $1 / $5     Opus 4.x $15 / $75  Sonnet 4.x $3 / $15
# cache_write 统一按 5 分钟缓存 = 1.25 × input（与既有条目口径一致）。
#
# Sonnet 5 的 $2/$10 是** introductory 价，2026-08-31 结束**，2026-09-01 起
# 标准价 $3/$15。此处刻意取标准价：成本**高估**会让预算闸提前触发，
# 是安全方向；低估才会导致实际超支。
#
# gpt-4.1（P2-5 补齐）：$2 / $8 / cache read $0.50（官方列表价）。此前缺失
# 导致该模型成本恒为 0。若条目过期，宁高勿低。
PRICES_USD_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-fable-5": {"input": 10.0, "output": 50.0, "cache_write": 12.5, "cache_read": 1.00},
    "claude-opus-5": {"input": 5.0, "output": 25.0, "cache_write": 6.25, "cache_read": 0.50},
    "claude-mythos-5": {"input": 5.0, "output": 25.0, "cache_write": 6.25, "cache_read": 0.50},
    "claude-opus-4": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet-5": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku-4": {"input": 1.0, "output": 5.0, "cache_write": 1.25, "cache_read": 0.10},
    "claude-opus": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku": {"input": 0.80, "output": 4.0, "cache_write": 1.0, "cache_read": 0.08},
    # 家族兜底：窗口表有 "claude-" 条目（200k），价格表此前没有 → 未知
    # Claude 型号成本恒为 0。按家族最贵的 opus 价兜底（宁高勿低）。
    "claude-": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "gpt-4o": {"input": 2.50, "output": 10.0, "cache_write": 2.50, "cache_read": 1.25},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_write": 0.15, "cache_read": 0.075},
    "gpt-5": {"input": 1.25, "output": 10.0, "cache_write": 1.25, "cache_read": 0.125},
    "gpt-4.1": {"input": 2.0, "output": 8.0, "cache_write": 2.5, "cache_read": 0.50},
    "gpt-4": {"input": 10.0, "output": 30.0, "cache_write": 10.0, "cache_read": 5.0},
    "deepseek-chat": {"input": 0.27, "output": 1.10, "cache_write": 0.27, "cache_read": 0.07},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19, "cache_write": 0.55, "cache_read": 0.14},
    "qwen": {"input": 0.4, "output": 1.2, "cache_write": 0.4, "cache_read": 0.1},
}
