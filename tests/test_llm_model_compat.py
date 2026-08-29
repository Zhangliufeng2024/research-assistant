"""Anthropic 采样参数守卫 + 模型元数据表（上下文窗口 / 价格）。

背景（2026-08-28 联网核实）：Anthropic 自 **Opus 4.7** 起对**非默认**
temperature / top_p / top_k 返回 HTTP 400，该限制延续到 Opus 4.8、Opus 5、
Sonnet 5、Fable 5、Mythos 5 与 Mythos Preview。Haiku 4.5 是例外，仍接受
（但 temperature 与 top_p 不可同时给）。

项目默认模型正是 ``claude-sonnet-5``，默认 temperature 为 0.5（RunConfig）
/ 0.7（chat）——都是非默认值。若无条件下发，新用户只填 API Key、不指定
模型时**每一通请求都会 400**。

本文件同时锁死三个极易被"改回去"的点：

1. 正则必须按**主版本号**判断。Claude 5 的 ID 丢掉了 minor 段
   （claude-opus-4-8 → claude-opus-5），任何按 ``-4-`` 结构匹配的判断
   都会对 5.x **静默失配**，于是照发 temperature、于是每条请求 400。
2. ``window_for()`` 是**首个匹配即返回**，版本级条目必须排在家族兜底之前。
3. ``price_for()`` 是**最长前缀**匹配，版本级条目优先于家族兜底。

判定原则：**未知即放行**——守卫只修已知会 400 的模型，绝不能让今天还能
正常工作的 provider 因守卫而失效。
"""

from __future__ import annotations

import json

import httpx
import pytest

from research_assistant.kernel.budget import price_for
from research_assistant.kernel.context import window_for
from research_assistant.llm.anthropic import AnthropicClient, supports_sampling_params

# ---------------------------------------------------------------------------
# 1. supports_sampling_params：模型族判定
# ---------------------------------------------------------------------------


class TestSupportsSamplingParams:
    """拒绝采样参数的模型（返回 False）。"""

    @pytest.mark.parametrize(
        "model",
        [
            "claude-sonnet-5",          # 项目默认模型
            "claude-opus-5",
            "claude-fable-5",
            "claude-mythos-5",
            "claude-opus-4-7",
            "claude-opus-4-8",
            "claude-mythos-preview",
        ],
    )
    def test_rejects(self, model: str):
        assert supports_sampling_params(model) is False

    """接受采样参数的模型（返回 True）。"""

    @pytest.mark.parametrize(
        "model",
        [
            "claude-sonnet-4-6",
            "claude-opus-4-6",
            "claude-opus-4-5",
            "claude-haiku-4-5-20251001",   # Haiku 4.5 例外：仍接受
            "claude-3-7-sonnet-20250219",
            "claude-3-5-sonnet-20241022",
            "gpt-4o",
            "deepseek-chat",
        ],
    )
    def test_accepts(self, model: str):
        assert supports_sampling_params(model) is True

    @pytest.mark.parametrize("model", ["claude-SONNET-5", "  claude-sonnet-5  ", "Claude-Opus-4-7"])
    def test_case_and_whitespace_insensitive(self, model: str):
        """大小写与空白不应影响判定（模型 ID 可能来自用户手填的 .env）。"""
        assert supports_sampling_params(model) is False

    @pytest.mark.parametrize("model", ["", "my-custom-model", "gpt-5", "qwen-plus"])
    def test_unknown_models_pass_through(self, model: str):
        """未知即放行：守卫不得让今天还能用的 provider 失效。"""
        assert supports_sampling_params(model) is True

    def test_future_5x_with_minor_segment_still_rejected(self):
        """claude-opus-5-1 之类带 minor 段的未来 ID 也必须拒绝。"""
        assert supports_sampling_params("claude-opus-5-1") is False

    def test_future_4x_double_digit_minor_rejected(self):
        """claude-opus-4-10（minor 两位数，晚于 4.7）必须拒绝。"""
        assert supports_sampling_params("claude-opus-4-10") is False

    def test_haiku_45_dated_snapshot_not_caught_by_47_rule(self):
        """回归锁：haiku-4-5 的 minor 是 5，不得被 4.7+ 规则误伤。"""
        assert supports_sampling_params("claude-haiku-4-5") is True
        assert supports_sampling_params("claude-haiku-4-7") is False


# ---------------------------------------------------------------------------
# 2. 请求体构造：只在支持时下发 temperature
# ---------------------------------------------------------------------------


def _capturing_client(model: str) -> tuple[AnthropicClient, dict]:
    """返回一个把请求体写进 captured 字典的 Anthropic 客户端（不触网）。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    client = AnthropicClient(api_key="test-key", model=model)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client, captured


class TestRequestBodySamplingParams:
    async def test_omits_temperature_for_sonnet_5(self):
        """核心回归：默认模型不得下发 temperature，否则每条请求 400。"""
        client, body = _capturing_client("claude-sonnet-5")
        await client.chat([{"role": "user", "content": "hi"}], temperature=0.5)
        assert "temperature" not in body
        assert body["model"] == "claude-sonnet-5"
        # max_tokens 未被弃用，必须保留
        assert "max_tokens" in body

    async def test_omits_temperature_for_opus_47(self):
        client, body = _capturing_client("claude-opus-4-7")
        await client.chat([{"role": "user", "content": "hi"}], temperature=0.5)
        assert "temperature" not in body

    async def test_sends_temperature_for_sonnet_46(self):
        """反向断言：老模型行为必须保持不变（防"修完把正常功能也堵了"）。"""
        client, body = _capturing_client("claude-sonnet-4-6")
        await client.chat([{"role": "user", "content": "hi"}], temperature=0.5)
        assert body["temperature"] == 0.5

    async def test_sends_temperature_for_haiku_45(self):
        client, body = _capturing_client("claude-haiku-4-5-20251001")
        await client.chat([{"role": "user", "content": "hi"}], temperature=0.3)
        assert body["temperature"] == 0.3

    async def test_streaming_path_also_guarded(self):
        """流式与非流式共用同一个 body 构造点，必须同样受保护。"""
        client, body = _capturing_client("claude-sonnet-5")

        chunks: list[str] = []
        await client.chat(
            [{"role": "user", "content": "hi"}],
            temperature=0.5,
            on_chunk=lambda _t: chunks.append(_t),
        )
        assert "temperature" not in body
        assert body.get("stream") is True


# ---------------------------------------------------------------------------
# 3. 上下文窗口表
# ---------------------------------------------------------------------------


class TestContextWindows:
    @pytest.mark.parametrize(
        "model",
        ["claude-sonnet-5", "claude-opus-5", "claude-fable-5", "claude-mythos-5"],
    )
    def test_claude_5_is_one_million(self, model: str):
        """回归锁：此前整族写成 200_000，导致 1M 窗口的模型在 140k 就压缩。"""
        assert window_for(model) == 1_000_000

    @pytest.mark.parametrize("model", ["claude-opus-4-6", "claude-opus-4-5", "claude-sonnet-4-6"])
    def test_claude_4x_stays_200k(self, model: str):
        assert window_for(model) == 200_000

    def test_haiku_45_stays_200k(self):
        assert window_for("claude-haiku-4-5-20251001") == 200_000

    def test_unknown_model_falls_back(self):
        assert window_for("totally-unknown") == 128_000

    def test_compaction_trigger_uses_full_window(self):
        """1M 窗口下，触发阈值应为 700k 而非 140k。"""
        from research_assistant.kernel.context import COMPACTION_TRIGGER_FRACTION

        assert int(window_for("claude-sonnet-5") * COMPACTION_TRIGGER_FRACTION) == 700_000


# ---------------------------------------------------------------------------
# 4. 价格表
# ---------------------------------------------------------------------------


class TestPrices:
    def test_opus_5_not_triple_counted(self):
        """回归锁：此前 claude-opus 一栏写成 15/75，对 Opus 5（5/25）3 倍高估。"""
        p = price_for("claude-opus-5")
        assert p["input"] == 5.0
        assert p["output"] == 25.0

    def test_opus_4x_keeps_legacy_price(self):
        p = price_for("claude-opus-4-6")
        assert p["input"] == 15.0
        assert p["output"] == 75.0

    def test_fable_5_has_an_entry(self):
        """此前 fable 完全缺失 → 未知模型 → 成本上限静默失效。"""
        p = price_for("claude-fable-5")
        assert p["input"] == 10.0
        assert p["output"] == 50.0

    def test_sonnet_5_uses_standard_price(self):
        """刻意取标准价 3/15（2026-09-01 起生效）而非 intro 价 2/10：
        成本高估会让预算闸提前触发，是安全方向。"""
        p = price_for("claude-sonnet-5")
        assert p["input"] == 3.0
        assert p["output"] == 15.0

    def test_haiku_45_price(self):
        p = price_for("claude-haiku-4-5-20251001")
        assert p["input"] == 1.0
        assert p["output"] == 5.0

    def test_unknown_model_is_zero_priced(self):
        p = price_for("no-such-model")
        assert p["input"] == 0.0
        assert p["output"] == 0.0

    def test_cache_write_is_125x_input(self):
        """既有口径：5 分钟缓存写入 = 1.25 × input。新增条目必须沿用。"""
        for model in ("claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-haiku-4-5"):
            p = price_for(model)
            assert p["cache_write"] == pytest.approx(p["input"] * 1.25), model


# ---------------------------------------------------------------------------
# 5. 未知模型时预算闸必须显式告警（而非静默显示 $0.00）
# ---------------------------------------------------------------------------


class TestUnknownModelBudgetWarning:
    def test_set_model_warns_when_unpriced(self, monkeypatch, caplog):
        """回归锁：set_model 此前静默放行，前端会显示 $0.00。"""
        from research_assistant.kernel.budget import BudgetGuard, BudgetLimits

        monkeypatch.setenv("RA_MAX_COST_USD", "5")
        guard = BudgetGuard(
            limits=BudgetLimits(max_cost_usd=5.0), model="claude-sonnet-5"
        )
        with caplog.at_level("WARNING"):
            guard.set_model("totally-unknown-model")

        assert any("unpriced" in r.message or "unenforceable" in r.message
                   for r in caplog.records)
        assert guard.cost_cap_enforceable is False
