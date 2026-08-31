"""P2-5 回归锁：模型窗口表与价格表的覆盖一致性。

两张表此前各自维护（窗口在 context.py、价格在 budget.py），匹配语义也不同
（first-match / longest-prefix），于是出现 ``gpt-4.1`` 有窗口条目（1M）却无
价格条目 → ``price_for`` 落到零价默认 → **成本恒为 0**，
``BudgetGuard.cost_cap_enforceable`` 静默退化为 False，成本上限形同虚设。

数据已收敛到 ``kernel/model_registry.py``（单一来源）。本文件不验证匹配语义
（那是 context/budget 自己的测试），只验证**覆盖一致性**：凡是有窗口条目的
模型，必须有非零价格；反过来价格表里的条目也不该是零价——任一条被改动而
另一条没跟上，这里立刻报警。
"""

import pytest

from research_assistant.kernel.budget import price_for
from research_assistant.kernel.context import window_for
from research_assistant.kernel.model_registry import (
    DEFAULT_CONTEXT_WINDOW,
    MODEL_WINDOWS,
    PRICES_USD_PER_MTOK,
)


class TestModelRegistryConsistency:
    @pytest.mark.parametrize("prefix,window", MODEL_WINDOWS)
    def test_every_window_entry_has_nonzero_price(self, prefix, window):
        price = price_for(prefix)
        assert price["input"] > 0, (
            f"模型前缀 {prefix!r} 有窗口条目但价格缺失/为零——"
            "成本会被静默计为 0，预算闸随之失效"
        )
        assert price["output"] > 0, prefix

    @pytest.mark.parametrize("prefix,price", sorted(PRICES_USD_PER_MTOK.items()))
    def test_no_zero_price_entries(self, prefix, price):
        """价格表里不允许全零条目（全零 = 没配置，等于没有这张表）。"""
        assert price["input"] > 0, prefix
        assert price["output"] > 0, prefix
        assert price["cache_read"] >= 0, prefix

    def test_regression_gpt41_cost_not_zero(self):
        """原始缺陷的定点回归：gpt-4.1 曾有窗口无价格。"""
        assert window_for("gpt-4.1") == 1_000_000
        assert price_for("gpt-4.1")["input"] > 0

    def test_unknown_model_falls_back_to_conservative_defaults(self):
        """未知名仍走保守兜底（128k 窗口 + 零价默认不变）。"""
        assert window_for("totally-unknown-model") == DEFAULT_CONTEXT_WINDOW
        # 零价兜底本身允许存在（未知模型无法计价），但已知前缀必须非零
        assert window_for("") == DEFAULT_CONTEXT_WINDOW

    def test_price_longest_prefix_still_wins(self):
        """收敛不得改变匹配语义：版本级价格优先于家族兜底。"""
        # claude-opus-5（版本级 $5）不得被 claude-opus（$15）截走
        assert price_for("claude-opus-5")["input"] == 5.0
        assert price_for("claude-opus-4-1")["input"] == 15.0
