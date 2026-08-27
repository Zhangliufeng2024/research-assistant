"""R9 回归：LLM 调用监督（两阶段看门狗 / 墙钟兜底 / 停止可打断）。

背景（用户反馈「永久思考中」）：旧实现把看门狗套在重试循环外面——首字节
前静默要等满 300s 且不重试；keepalive 滴流可无限续期；cancel_event 打不断
在途调用。这里逐条锁死修复行为。
"""

import asyncio
import time

import pytest

from research_assistant.agent import (
    _ActivityWatchdog,
    _cancelable,
    _TurnCancelled,
    run_agent,
)
from research_assistant.llm.base import LLMResponse
from research_assistant.llm.errors import HeartbeatTimeoutError
from research_assistant.models import TokenUsage


class _HangNoBeatClient:
    """接受连接但永不吐字节：应在首字节窗口内快失败。"""

    model = "fake"

    async def chat(self, messages, **kwargs):
        on_activity = kwargs.get("on_activity")
        if on_activity is not None:  # 永不 beat
            await asyncio.Event().wait()
        await asyncio.Event().wait()

    async def close(self):
        pass


class _DripKeepaliveClient:
    """每 20ms 滴一行 keepalive 心跳、永不产出内容：只能靠墙钟兜底击杀。"""

    model = "fake"

    async def chat(self, messages, on_activity=None, **kwargs):
        while True:
            await asyncio.sleep(0.02)
            if on_activity is not None:
                on_activity()

    async def close(self):
        pass


class _RecoverClient:
    """第一次挂起（触发心跳超时），第二次正常返回：证明超时后真的会重试。"""

    model = "fake"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            await asyncio.Event().wait()  # 挂死，等看门狗击杀
        return LLMResponse(content="ok", usage=TokenUsage())

    async def close(self):
        pass


@pytest.mark.asyncio()
class TestWatchdog:
    async def test_first_byte_fast_fail(self):
        """无任何心跳：按首字节窗口（而非静默大窗）快失败。"""
        wd = _ActivityWatchdog(timeout=60.0, first_byte_timeout=0.2)
        t0 = time.monotonic()
        with pytest.raises(HeartbeatTimeoutError) as ei:
            await wd.call(lambda: _HangNoBeatClient().chat([]))
        assert time.monotonic() - t0 < 2.0
        assert "首字节" in str(ei.value)

    async def test_first_byte_window_not_poisoned_by_previous_attempt(self):
        """同一重试循环的上一次尝试残留心跳，不得为本次首字节窗续命。"""
        wd = _ActivityWatchdog(timeout=60.0, first_byte_timeout=0.2)

        class _BeatOnceThenOK:
            model = "fake"

            async def chat(self, messages, on_activity=None, **kwargs):
                if on_activity is not None:  # 模拟流式心跳后正常完成
                    on_activity()
                return LLMResponse(content="partial", usage=TokenUsage())

        await wd.call(lambda: _BeatOnceThenOK().chat([]))  # 尝试1：留下一活动标记

        t0 = time.monotonic()
        with pytest.raises(HeartbeatTimeoutError) as ei:
            await wd.call(lambda: _HangNoBeatClient().chat([]))  # 尝试2：静默悬挂
        assert time.monotonic() - t0 < 2.0  # 若被污染会退化为 60s 静默窗
        assert "首字节" in str(ei.value)

    async def test_wall_timeout_kills_endless_keepalive_drip(self):
        """滴流续期静默看门狗也逃不过墙钟兜底。"""
        wd = _ActivityWatchdog(
            timeout=0.15, first_byte_timeout=0.15, wall_timeout=0.5
        )
        t0 = time.monotonic()
        with pytest.raises(HeartbeatTimeoutError) as ei:
            # 直连看门狗时需手动接线心跳（run_agent 里由 _do_call 完成）
            await wd.call(lambda: _DripKeepaliveClient().chat([], on_activity=wd.beat))
        assert time.monotonic() - t0 < 3.0
        assert "总时长" in str(ei.value)

    async def test_healthy_long_stream_not_killed(self):
        """持续心跳 + 最终返回：健康长流不被误杀。"""

        class _SlowOK:
            model = "fake"

            async def chat(self, messages, on_activity=None, **kwargs):
                for _ in range(6):  # 总时长 > 静默窗，但有心跳续期
                    await asyncio.sleep(0.08)
                    if on_activity:
                        on_activity()
                return LLMResponse(content="done", usage=TokenUsage())

            async def close(self):
                pass

        wd = _ActivityWatchdog(timeout=0.15)
        assert (await wd.call(lambda: _SlowOK().chat([], on_activity=wd.beat))).content == "done"


@pytest.mark.asyncio()
class TestCancelable:
    async def test_stop_interrupts_inflight_call(self):
        """cancel_event 置位立即打断挂死中的调用（旧实现毫无作用）。"""
        event = asyncio.Event()
        task = asyncio.create_task(
            _cancelable(_HangNoBeatClient().chat([]), event)
        )
        await asyncio.sleep(0.05)
        t0 = asyncio.get_running_loop().time()
        event.set()
        with pytest.raises(_TurnCancelled):
            await asyncio.wait_for(task, timeout=2.0)
        assert asyncio.get_running_loop().time() - t0 < 1.5

    async def test_result_passthrough_without_event(self):
        assert await _cancelable(coro_factory_result(), None) == "ok"

    async def test_exception_passthrough(self):
        event = asyncio.Event()

        async def _boom():
            raise RuntimeError("x")

        with pytest.raises(RuntimeError):
            await _cancelable(_boom(), event)


async def coro_factory_result():
    await asyncio.sleep(0)
    return "ok"


@pytest.mark.asyncio()
class TestRunAgentIntegration:
    async def test_heartbeat_timeout_then_retry_succeeds(self, monkeypatch):
        monkeypatch.setenv("RA_LLM_FIRST_BYTE_TIMEOUT", "0.2")
        monkeypatch.setenv("RA_RETRY_BASE_DELAY", "0.05")
        """看门狗超时异常现在落在重试循环内：第二次尝试成功即整体成功。

        （旧行为：watchdog 包在重试循环外，HeartbeatTimeoutError 直接炸出，
        retryable 形同虚设。）
        """
        from research_assistant.agent import RunConfig
        from research_assistant.tools.registry import ToolRegistry

        client = _RecoverClient()
        result = await run_agent(
            prompt="hi",
            system_prompt="",
            llm_client=client,
            tools=ToolRegistry(),
            config=RunConfig(max_turns=2, auto_continue=False),
            max_tokens=16,
        )
        assert client.calls == 2
        assert result.success and result.text_output == "ok"

    async def test_stop_during_inflight_llm_call_ends_run_cancelled(self):
        """run_agent 内置取消：停止事件打断挂死的 LLM 调用 → cancelled 收场。"""
        from research_assistant.agent import RunConfig
        from research_assistant.tools.registry import ToolRegistry

        cancel = asyncio.Event()
        client = _HangNoBeatClient()

        async def _stop_later():
            await asyncio.sleep(0.3)
            cancel.set()

        stopper = asyncio.create_task(_stop_later())
        result = await run_agent(
            prompt="hi",
            system_prompt="",
            llm_client=client,
            tools=ToolRegistry(),
            config=RunConfig(max_turns=2, heartbeat_timeout=30.0, cancel_event=cancel),
            max_tokens=16,
        )
        await stopper
        assert result.stop_reason == "cancelled"
