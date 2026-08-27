"""P1 回归：压缩摘要接 LLM 监督 + 外部化产物同名覆盖。

背景（两个缺陷同在 kernel/context.py）：

- 缺陷 A（「永久思考中」压缩路径残留）：``maybe_compact → summarize_span``
  裸调 ``llm_client.chat``，完全绕过 run_agent 的两阶段看门狗 / cancel_event
  打断 / 重试设施——一次挂死的摘要请求既不会被击杀也不会被「停止」打断，
  用户点停止毫无作用。
- 缺陷 B（审计失真）：``externalize_tool_result`` 落盘文件名不含调用序号
  （``turn_NNNN_<tool>.txt``），同轮两次同名工具第二次覆盖第一次。

监督接线契约：ContextManager 侧（本仓库为 context.py 的函数式 API）新增可
注入回调 *supervised_chat*——由 run_agent 把自己内部带看门狗+取消+重试的
调用工厂传进来；未提供时回退裸调以兼容旧构造方。
"""

import asyncio
import logging
import re
import time
from pathlib import Path

from research_assistant.agent import RunConfig, _TurnCancelled, run_agent
from research_assistant.kernel.context import (
    externalize_tool_result,
    maybe_compact,
    summarize_span,
)
from research_assistant.llm.base import LLMResponse
from research_assistant.models import TokenUsage

# ---------------------------------------------------------------------------
# 桩
# ---------------------------------------------------------------------------

class _ScriptedClient:
    """按脚本逐次响应的假客户端：脚本耗尽后永久挂死。

    chat 不声明 on_activity 具名参数 → run_agent 视为不支持活动心跳，
    看门狗走首字节快失败窗口（与 test_llm_supervision 的桩手法一致）。
    """

    model = "fake"

    def __init__(self, script=()):
        self.script = list(script)
        self.calls = 0
        self.prompts: list[str] = []

    async def chat(self, messages, **kwargs):
        self.calls += 1
        self.prompts.append(messages[-1]["content"])
        if self.script:
            item = self.script.pop(0)
            if item == "hang":
                await asyncio.Event().wait()  # 挂死，直到被看门狗/取消击杀
            return item
        await asyncio.Event().wait()

    async def close(self):
        pass


class _BareCallForbiddenClient(_ScriptedClient):
    """裸调即失败——证明摘要走了注入的 supervised_chat。"""

    async def chat(self, messages, **kwargs):
        raise AssertionError("bare llm_client.chat must not be called when "
                             "supervised_chat is injected")


class _SessionLog:
    def __init__(self):
        self.entries: list[tuple[str, dict]] = []

    def log(self, kind, data):
        self.entries.append((kind, data))


def _ok_main_response(content="main answer"):
    """主链路响应：input_tokens 超触发线（128k×0.7=89600），驱动压缩。"""
    return LLMResponse(content=content, usage=TokenUsage(input_tokens=100_000))


def _summary_response(text="## Goal\nsummarized\n"):
    return LLMResponse(content=text)


def _long_history(n_exchanges=20):
    msgs = [{"role": "user", "content": "write a paper"}]
    for i in range(n_exchanges):
        msgs.extend([
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": f"c{i}", "name": "bash", "arguments": {"command": f"cmd{i}"}},
            ]},
            {"role": "tool", "tool_call_id": f"c{i}", "content": f"result {i}"},
        ])
    return msgs


def _run_config(client_script, **kw):
    log = _SessionLog()
    cfg_kw = dict(
        max_turns=2,
        auto_continue=False,
        compaction=True,
        session_log=log,
        externalize_outputs=False,
        # 长历史进初始消息：主调用后 measured tokens 超触发线且存在可压缩段，
        # 摘要调用才真的会发生。
        initial_messages=_long_history(),
    )
    cfg_kw.update(kw)
    return RunConfig(**cfg_kw), log


# ---------------------------------------------------------------------------
# 缺陷 A-1：挂死的摘要请求被看门狗首字节窗击杀（而非无限等待）
# ---------------------------------------------------------------------------

class TestHungSummaryKilledByWatchdog:
    async def test_hung_summary_killed_in_first_byte_window_run_degrades(
        self, monkeypatch, caplog,
    ):
        """摘要客户端挂死 → 首字节窗内抛 HeartbeatTimeoutError；压缩按既有
        语义优雅降级（警告 + 运行继续），但绝不能无限等下去。"""
        monkeypatch.setenv("RA_LLM_FIRST_BYTE_TIMEOUT", "0.2")
        monkeypatch.setenv("RA_MAX_RETRIES", "0")  # 单次尝试即可观察击杀
        monkeypatch.setenv("RA_RETRY_BASE_DELAY", "0.05")
        caplog.set_level(logging.WARNING, logger="research_assistant.agent")

        # 脚本：第 1 次 = 主链路正常返回（大 input_tokens 触发压缩）；
        # 第 2 次 = 摘要请求永久挂死。
        client = _ScriptedClient([_ok_main_response()])
        cfg, _log = _run_config(client)
        t0 = time.monotonic()
        result = await asyncio.wait_for(
            run_agent(
                prompt="hi",
                system_prompt="",
                llm_client=client,
                tools=_noop_tools(),
                config=cfg,
            ),
            timeout=15,
        )
        elapsed = time.monotonic() - t0

        assert result.success and result.text_output == "main answer"
        # 若回归为裸调：挂死永不返回（wait_for 会先炸）；这里再锁一个宽松上限。
        assert elapsed < 10, f"hung summary was not killed quickly ({elapsed:.1f}s)"
        # 击杀证据：降级警告里带着看门狗的首字节超时异常。
        assert "上下文压缩失败" in caplog.text
        assert "No output received" in caplog.text
        assert client.calls == 2  # 主调用 + 恰一次（不重试）摘要尝试

    async def test_summary_timeout_retried_then_compaction_succeeds(self, monkeypatch):
        """看门狗杀掉第一次摘要尝试后重试成功 → 压缩整体成功
        （参照 test_llm_supervision.TestRunAgentIntegration 的桩手法）。"""
        monkeypatch.setenv("RA_LLM_FIRST_BYTE_TIMEOUT", "0.2")
        monkeypatch.setenv("RA_MAX_RETRIES", "3")
        monkeypatch.setenv("RA_RETRY_BASE_DELAY", "0.05")

        client = _ScriptedClient([
            _ok_main_response(),
            "hang",                      # 摘要尝试 1：挂死 → 首字节窗击杀
            _summary_response(),         # 摘要尝试 2：成功
        ])
        cfg, log = _run_config(client)
        result = await asyncio.wait_for(
            run_agent(
                prompt="hi",
                system_prompt="",
                llm_client=client,
                tools=_noop_tools(),
                config=cfg,
            ),
            timeout=15,
        )

        assert result.success
        assert client.calls == 3  # 主 + 两次摘要尝试
        assert any(kind == "compaction" for kind, _ in log.entries), (
            "compaction should have succeeded after retry"
        )


def _noop_tools():
    from research_assistant.tools.registry import ToolRegistry

    return ToolRegistry()


# ---------------------------------------------------------------------------
# 缺陷 A-2：取消语义穿透降级逻辑
# ---------------------------------------------------------------------------

class TestCancelDuringCompaction:
    async def test_stop_interrupts_hung_summary_ends_run_cancelled(self, monkeypatch):
        """用户点停止时挂死中的摘要必须被打断，且取消不得被「压缩失败照常
        继续」的降级逻辑吞掉——run 以 cancelled 干净收场。"""
        monkeypatch.setenv("RA_LLM_FIRST_BYTE_TIMEOUT", "60")  # 大窗：看门狗不动手
        monkeypatch.setenv("RA_MAX_RETRIES", "0")

        client = _ScriptedClient([_ok_main_response()])  # 之后全部挂死
        cancel = asyncio.Event()
        cfg, _log = _run_config(client, heartbeat_timeout=300.0, cancel_event=cancel)

        async def _stop_later():
            await asyncio.sleep(0.3)
            cancel.set()

        stopper = asyncio.create_task(_stop_later())
        try:
            result = await asyncio.wait_for(
                run_agent(
                    prompt="hi",
                    system_prompt="",
                    llm_client=client,
                    tools=_noop_tools(),
                    config=cfg,
                ),
                timeout=15,
            )
        finally:
            stopper.cancel()
        assert result.stop_reason == "cancelled"

    async def test_turn_cancelled_propagates_through_maybe_compact(self):
        """契约锁死：supervised_chat 抛出的 _TurnCancelled 必须原样穿出
        maybe_compact——context 层不做任何降级吞没（降级只属于调用方）。"""
        msgs = _long_history()

        async def _cancelled_chat(**kwargs):
            raise _TurnCancelled()

        try:
            await maybe_compact(
                msgs,
                llm_client=None,
                model="fake",
                last_input_tokens=100_000,
                supervised_chat=_cancelled_chat,
            )
        except _TurnCancelled:
            pass  # 期望路径
        else:
            raise AssertionError("_TurnCancelled was swallowed by maybe_compact")


# ---------------------------------------------------------------------------
# 缺陷 A-3：注入与回退契约
# ---------------------------------------------------------------------------

class TestSupervisedChatInjection:
    async def test_summarize_span_prefers_supervised_chat(self):
        """注入 supervised_chat 时摘要走回调（裸调禁用），kwargs 齐全，
        预算计量照常。"""

        captured = {}

        async def _supervised(**kwargs):
            captured.update(kwargs)
            return _summary_response("  supervised summary  ")

        class _RecordingBudget:
            def __init__(self):
                self.recorded = []

            def record(self, response):
                self.recorded.append(response)

        budget = _RecordingBudget()
        summary = await summarize_span(
            _BareCallForbiddenClient(), "span text",
            budget=budget, supervised_chat=_supervised,
        )

        assert summary == "supervised summary"
        assert captured["messages"] == [{"role": "user", "content": "span text"}]
        assert captured["max_tokens"] == 1600
        assert "system" in captured and "temperature" in captured
        assert len(budget.recorded) == 1

    async def test_maybe_compact_routes_summary_through_supervised_chat(self):
        msgs = _long_history()
        seen = []

        async def _supervised(*, messages, system, temperature, max_tokens):
            seen.append(messages[-1]["content"])
            return _summary_response()

        out, compacted, info = await maybe_compact(
            msgs,
            llm_client=_BareCallForbiddenClient(),
            model="claude-sonnet-5",
            last_input_tokens=190_000,
            supervised_chat=_supervised,
        )

        assert compacted
        assert len(seen) == 1
        assert "[CONTEXT SUMMARY" in str(out[1]["content"])

    async def test_without_supervised_chat_falls_back_to_bare_call(self):
        """旧构造方兼容：未注入回调时行为与现状一致（裸调不报错）。"""
        client = _ScriptedClient([_summary_response("## Goal\nlegacy path\n")])
        summary = await summarize_span(client, "span text")
        assert "legacy path" in summary
        assert client.calls == 1


# ---------------------------------------------------------------------------
# 缺陷 B：外部化同名工具同轮覆盖
# ---------------------------------------------------------------------------

class TestExternalizeSameNameNoOverwrite:
    def test_same_turn_same_tool_writes_distinct_files(self, tmp_path):
        r1 = externalize_tool_result("a" * 5_000, "read_file", 7, tmp_path)
        r2 = externalize_tool_result("b" * 6_000, "read_file", 7, tmp_path)

        files = sorted(p.name for p in tmp_path.iterdir())
        assert len(files) == 2, f"second call overwrote the first: {files}"
        assert len(set(files)) == 2

        # 两份预览各自引用自己那份文件，引用的文件都真实存在、内容对应。
        def pointer(out):
            match = re.search(r"saved to: (\S+)", out)
            assert match, out[-200:]
            return match.group(1)

        p1, p2 = pointer(r1), pointer(r2)
        assert p1 != p2
        assert p1.endswith(files[0]) or p1.endswith(files[1])
        assert p2.endswith(files[0]) or p2.endswith(files[1])
        assert Path(p1).read_text(encoding="utf-8") == "a" * 5_000
        assert Path(p2).read_text(encoding="utf-8") == "b" * 6_000

    def test_three_calls_same_tool_same_turn_all_preserved(self, tmp_path):
        for i in range(3):
            externalize_tool_result((f"payload-{i} ") * 500, "bash", 3, tmp_path)
        heads = sorted(p.read_text(encoding="utf-8")[:20] for p in tmp_path.iterdir())
        assert len(heads) == 3
        assert set(heads) == {(f"payload-{i} " * 500)[:20] for i in range(3)}

    def test_first_write_keeps_legacy_name(self, tmp_path):
        """兼容锁死：首次落盘沿用旧命名（turn_NNNN_tool.txt），只有碰撞才加序号。"""
        externalize_tool_result("x" * 10_000, "read_file", 7, tmp_path)
        names = [p.name for p in tmp_path.iterdir()]
        assert names == ["turn_0007_read_file.txt"]
