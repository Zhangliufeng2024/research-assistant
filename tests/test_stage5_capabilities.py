"""A+ 阶段 5：模型 fallback 链与子进程环境净化。

**G-5 fallback**：此前 factory 只能二选一，主模型不可用即整个任务失败。
**G-4 净化**：此前 bash / run_python 的子进程继承完整 os.environ，
``os.environ["LLM_API_KEY"]`` 一行即可读走全部密钥。

两者都是"消除单点"性质的最小改动，测试重点：
  - fallback：降级真的发生、最后一个候选的异常原样上抛（绝不吞错）、
    不配置时行为与现状完全一致；
  - 净化：密钥确实被剔除、非密钥变量确实保留（反向断言防"净化成空"）。
"""

from __future__ import annotations

import asyncio
import os

import pytest

from research_assistant.llm.base import LLMClient, LLMResponse
from research_assistant.llm.factory import create_llm_client
from research_assistant.llm.fallback import FallbackLLMClient
from research_assistant.tools.exec_provider import sanitized_exec_env

# ---------------------------------------------------------------------------
# FallbackLLMClient
# ---------------------------------------------------------------------------


class _ScriptedClient(LLMClient):
    """按脚本行为响应：抛错或返回。记录收到的调用。"""

    def __init__(self, *, model: str = "m", fail_times: int = 0, error: Exception | None = None):
        super().__init__()
        self.model = model
        self.fail_times = fail_times
        self.error = error or RuntimeError("主模型故障")
        self.calls = 0
        self.closed = False

    async def close(self) -> None:
        self.closed = True
        return None

    async def chat(self, messages, *, system="", tools=None, temperature=0.7,
                   max_tokens=16384, on_chunk=None, on_activity=None, on_thought=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error
        return LLMResponse(
            content=f"from-{self.model}", stop_reason="end_turn",
            usage=__import__("research_assistant.models", fromlist=["TokenUsage"]).TokenUsage(
                input_tokens=1, output_tokens=1,
            ),
        )


class _ChunkThenFail(_ScriptedClient):
    """先吐若干增量再失败——用于验证「已发布正文则不降级」。"""

    def __init__(self, *, chunks: list[str], **kw):
        super().__init__(**kw)
        self.chunks = list(chunks)

    async def chat(self, messages, *, system="", tools=None, temperature=0.7,
                   max_tokens=16384, on_chunk=None, on_activity=None, on_thought=None):
        self.calls += 1
        for delta in self.chunks:
            if on_chunk is not None:
                result = on_chunk(delta)
                if result is not None:
                    await result
        raise RuntimeError("吐字后失败")


class TestFallbackChain:
    def test_primary_success_no_fallback(self):
        primary = _ScriptedClient(model="primary")
        backup = _ScriptedClient(model="backup")
        chain = FallbackLLMClient([primary, backup], labels=["p", "b"])

        out = asyncio.run(chain.chat([{"role": "user", "content": "hi"}]))

        assert out.content == "from-primary"
        assert primary.calls == 1 and backup.calls == 0

    def test_falls_back_on_primary_failure(self):
        primary = _ScriptedClient(model="primary", fail_times=1)
        backup = _ScriptedClient(model="backup")
        chain = FallbackLLMClient([primary, backup], labels=["p", "b"])

        out = asyncio.run(chain.chat([{"role": "user", "content": "hi"}]))

        assert out.content == "from-backup"
        assert chain.active_index == 1

    def test_last_candidate_error_propagates(self):
        """红线：绝不吞错。最后一个候选的异常必须原样上抛，
        否则调用方的错误分类/重试/用户提示全部失灵。"""
        err = RuntimeError("最后的错误")
        primary = _ScriptedClient(model="p", fail_times=5, error=err)
        backup = _ScriptedClient(model="b", fail_times=5, error=err)
        chain = FallbackLLMClient([primary, backup])

        with pytest.raises(RuntimeError, match="最后的错误"):
            asyncio.run(chain.chat([{"role": "user", "content": "hi"}]))

    def test_all_candidates_are_tried(self):
        first = _ScriptedClient(model="a", fail_times=5)
        second = _ScriptedClient(model="b", fail_times=5)
        third = _ScriptedClient(model="c")
        chain = FallbackLLMClient([first, second, third])

        out = asyncio.run(chain.chat([{"role": "user", "content": "hi"}]))

        assert out.content == "from-c"
        assert first.calls == 1 and second.calls == 1 and third.calls == 1

    def test_rate_limit_errors_also_trigger_fallback(self):
        """限流也换候选：同一 provider 重试已由上层完成，仍失败说明短期
        不会好转，换 provider 是唯一有信息增量的动作。"""
        from research_assistant.llm.errors import RateLimitError

        primary = _ScriptedClient(
            model="p", fail_times=5,
            error=RateLimitError("429 quota exceeded", status_code=429, retry_after=1),
        )
        backup = _ScriptedClient(model="b")
        chain = FallbackLLMClient([primary, backup])

        out = asyncio.run(chain.chat([{"role": "user", "content": "hi"}]))
        assert out.content == "from-b"

    def test_empty_chain_is_rejected(self):
        with pytest.raises(ValueError):
            FallbackLLMClient([])

    # ---- P0-4：取消/中断语义不得被降级链吞掉 ----------------------------

    def test_cancellation_is_not_swallowed_by_fallback(self):
        """P0-4 红线：CancelledError 必须立即上抛。

        修复前 ``except BaseException`` 会把取消一并捕获并继续尝试下一个
        候选——用户点「停止」后本端仍向备选模型发一次完整请求并计费，
        取消语义彻底失效。
        """
        primary = _ScriptedClient(
            model="primary", fail_times=5, error=asyncio.CancelledError(),
        )
        backup = _ScriptedClient(model="backup")
        chain = FallbackLLMClient([primary, backup], labels=["p", "b"])

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(chain.chat([{"role": "user", "content": "hi"}]))

        assert backup.calls == 0, "取消后不得再向备选模型发起请求"

    def test_keyboard_interrupt_is_not_swallowed(self):
        """KeyboardInterrupt / SystemExit 同样不是「该候选不可用」的信号。"""
        primary = _ScriptedClient(
            model="primary", fail_times=5, error=KeyboardInterrupt(),
        )
        backup = _ScriptedClient(model="backup")
        chain = FallbackLLMClient([primary, backup])

        with pytest.raises(KeyboardInterrupt):
            asyncio.run(chain.chat([{"role": "user", "content": "hi"}]))

        assert backup.calls == 0

    # ---- P0-5：已发布正文后禁止降级 -------------------------------------

    def test_no_fallback_after_publishing_chunks(self):
        """P0-5 红线：吐过正文后失败不得换模型。

        换模型会让前后风格突变、内容重复，而**已发布的增量无法撤回**。
        这是 fallback.py docstring 早有承诺、但代码从未实现的语义。
        """
        primary = _ChunkThenFail(model="primary", chunks=["你好", "，世界"])
        backup = _ScriptedClient(model="backup")
        chain = FallbackLLMClient([primary, backup], labels=["p", "b"])

        seen: list[str] = []
        with pytest.raises(RuntimeError, match="吐字后失败"):
            asyncio.run(chain.chat(
                [{"role": "user", "content": "hi"}],
                on_chunk=seen.append,
            ))

        assert seen == ["你好", "，世界"], "增量必须完整透传给调用方"
        assert backup.calls == 0, "已发布正文后不得切换备选模型"

    def test_fallback_allowed_when_nothing_published(self):
        """对照组：尚未吐出任何增量时才允许降级（docstring 承诺的另一半）。"""
        primary = _ChunkThenFail(model="primary", chunks=[])
        backup = _ScriptedClient(model="backup")
        chain = FallbackLLMClient([primary, backup], labels=["p", "b"])

        out = asyncio.run(chain.chat(
            [{"role": "user", "content": "hi"}],
            on_chunk=lambda _d: None,
        ))

        assert out.content == "from-backup"
        assert backup.calls == 1

    def test_empty_delta_does_not_count_as_published(self):
        """空串增量不是「已发布」——心跳/空帧不应误伤降级能力。"""
        primary = _ChunkThenFail(model="primary", chunks=["", ""])
        backup = _ScriptedClient(model="backup")
        chain = FallbackLLMClient([primary, backup])

        out = asyncio.run(chain.chat(
            [{"role": "user", "content": "hi"}],
            on_chunk=lambda _d: None,
        ))

        assert out.content == "from-backup", "空增量不应阻断降级"

    def test_async_on_chunk_callback_is_awaited(self):
        """回调可能是协程函数（OnChunkCallback 允许返回 awaitable）——
        包装层必须 await 它，否则调用方的异步记账会静默丢失。"""
        primary = _ChunkThenFail(model="primary", chunks=["a"])
        chain = FallbackLLMClient([primary], labels=["p"])

        seen: list[str] = []

        async def slow_sink(delta: str) -> None:
            await asyncio.sleep(0)
            seen.append(delta)

        with pytest.raises(RuntimeError):
            asyncio.run(chain.chat(
                [{"role": "user", "content": "hi"}], on_chunk=slow_sink,
            ))

        assert seen == ["a"], "异步回调未被 await"

    def test_active_model_reflects_last_success(self):
        primary = _ScriptedClient(model="primary", fail_times=1)
        backup = _ScriptedClient(model="backup")
        chain = FallbackLLMClient([primary, backup])
        asyncio.run(chain.chat([{"role": "user", "content": "hi"}]))
        assert chain.model == "backup"

    def test_close_releases_all_candidates(self):
        """红线：close 必须关掉**所有**候选，不只活跃那个——切换过之后，
        失败候选的连接可能还挂在池里。"""
        a = _ScriptedClient(model="a")
        b = _ScriptedClient(model="b", fail_times=5)
        c = _ScriptedClient(model="c")
        chain = FallbackLLMClient([a, b, c])
        asyncio.run(chain.chat([{"role": "user", "content": "hi"}]))
        asyncio.run(chain.close())
        assert a.closed and b.closed and c.closed

    def test_close_failure_of_one_does_not_block_others(self):
        class Broken(_ScriptedClient):
            async def close(self) -> None:
                raise RuntimeError("close failed")

        a = _ScriptedClient(model="a")
        b = Broken(model="b")
        c = _ScriptedClient(model="c")
        chain = FallbackLLMClient([a, b, c])
        asyncio.run(chain.close())
        assert a.closed and c.closed, "单个候选 close 失败阻断了其它候选的释放"


# ---------------------------------------------------------------------------
# 工厂：RA_MODEL_FALLBACK 的解析
# ---------------------------------------------------------------------------


class TestFactoryFallbackConfig:
    def test_no_fallback_env_returns_plain_client(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-ant-test")
        monkeypatch.delenv("RA_MODEL_FALLBACK", raising=False)
        client = create_llm_client()
        assert not isinstance(client, FallbackLLMClient)

    def test_fallback_env_builds_chain(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-ant-test")
        monkeypatch.setenv("RA_MODEL_FALLBACK", "openai:gpt-4o,anthropic:claude-sonnet-5")
        chain = create_llm_client()
        assert isinstance(chain, FallbackLLMClient)
        assert len(chain.clients) == 3          # 主项 + 2 个备选
        assert len(chain.labels) == len(chain.clients)

    def test_bare_model_name_uses_primary_provider(self, monkeypatch):
        # 隔离环境：全量回归中前序测试可能经 load_project_env 写入
        # LLM_PROVIDER/LLM_BASE_URL（.env 残留），会让 provider 探测偏离
        # "sk-ant- 前缀 → anthropic" 的预期（既有 flake，顺手加固）。
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.setenv("LLM_API_KEY", "sk-ant-test")
        monkeypatch.setenv("RA_MODEL_FALLBACK", "claude-haiku-4-5")
        chain = create_llm_client()
        assert isinstance(chain, FallbackLLMClient)
        assert len(chain.clients) == 2
        # 裸模型名沿用主项 provider → 仍是 Anthropic 协议
        from research_assistant.llm.anthropic import AnthropicClient
        assert isinstance(chain.clients[1], AnthropicClient)

    def test_blank_segments_are_skipped(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-ant-test")
        monkeypatch.setenv("RA_MODEL_FALLBACK", " , openai:gpt-4o , ")
        chain = create_llm_client()
        assert isinstance(chain, FallbackLLMClient)
        assert len(chain.clients) == 2

    def test_empty_fallback_string_is_ignored(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-ant-test")
        monkeypatch.setenv("RA_MODEL_FALLBACK", "   ")
        assert not isinstance(create_llm_client(), FallbackLLMClient)


# ---------------------------------------------------------------------------
# 子进程环境净化（G-4）
# ---------------------------------------------------------------------------


class TestSanitizedExecEnv:
    def test_strips_known_secret_keys(self):
        env = sanitized_exec_env({
            "PATH": "/usr/bin",
            "LLM_API_KEY": "sk-secret",
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "OPENAI_API_KEY": "sk-secret",
            "IMAGE_API_KEY": "nvapi-secret",
        })
        assert env["PATH"] == "/usr/bin"
        assert not any("API_KEY" in k for k in env), f"密钥残留：{list(env)}"

    def test_strips_prefix_based_secrets(self):
        """前缀匹配：厂商清单永远追不全，按前缀兜住大部分。"""
        env = sanitized_exec_env({
            "MY_VENDOR_API_KEY": "x",
            "GITHUB_TOKEN": "x",
            "AWS_SECRET_ACCESS_KEY": "x",
            "DB_PASSWORD": "x",
            "HOME": "/home/me",
        })
        assert env == {"HOME": "/home/me"}, f"疑似密钥未被剔除：{sorted(env)}"

    def test_keeps_benign_variables(self):
        """反向断言：净化不能把正常变量也清掉（否则子进程跑不起来）。"""
        env = sanitized_exec_env({
            "PATH": "/usr/bin", "HOME": "/home", "SYSTEMROOT": "C:\\Windows",
            "PYTHONUTF8": "1", "LANG": "C.UTF-8", "TEMP": "C:\\Temp",
        })
        assert set(env) == {"PATH", "HOME", "SYSTEMROOT", "PYTHONUTF8", "LANG", "TEMP"}

    def test_case_insensitive_matching(self):
        env = sanitized_exec_env({"llm_api_key": "x", "Path": "/bin"})
        assert "llm_api_key" not in env
        assert env["Path"] == "/bin"

    def test_does_not_mutate_input(self):
        base = {"LLM_API_KEY": "x", "PATH": "/bin"}
        sanitized_exec_env(base)
        assert base == {"LLM_API_KEY": "x", "PATH": "/bin"}

    def test_defaults_to_process_environ(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-secret")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        env = sanitized_exec_env()
        assert "LLM_API_KEY" not in env

    def test_run_python_child_env_is_sanitized(self, tmp_path, monkeypatch):
        """端到端：模型代码里读不到 LLM_API_KEY，但能读到普通变量。"""
        from research_assistant.tools.python_exec import run_python

        monkeypatch.setenv("LLM_API_KEY", "sk-top-secret")
        monkeypatch.setenv("RA_TEST_BENIGN", "visible")
        code = (
            "import os\n"
            "print('KEY_PRESENT' if 'LLM_API_KEY' in os.environ else 'KEY_GONE')\n"
            "print('BENIGN_' + os.environ.get('RA_TEST_BENIGN', 'missing'))\n"
        )
        out = asyncio.run(run_python(code, cwd=str(tmp_path)))
        assert "KEY_GONE" in out, f"密钥仍在子进程环境：{out!r}"
        assert "BENIGN_visible" in out, "普通变量被误清"


class TestBashEnvSanitized:
    """bash 路径的净化（A+ 阶段 5 / G-4 收尾）。

    本机 run_python 修了、bash 漏了——这正是「净化放调用方自管」的失效模式：
    每新增一个执行工具都要记得做，漏一处就是密钥泄露面。修复把默认净化下沉到
    `_run_process` 这个所有模型子进程的唯一咽喉，调用方不再可能忘记。
    """

    def test_bash_child_env_is_sanitized(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-top-secret")
        monkeypatch.setenv("RA_TEST_BENIGN", "visible")
        if os.name == "nt":
            # cmd.exe 对已定义变量做展开、未定义的保留字面量——正好构成判别器：
            # 有净化 → 输出字面量 %LLM_API_KEY%；无净化 → 展开出真实密钥
            command = "echo KEY_%LLM_API_KEY%_ benign_%RA_TEST_BENIGN%"
        else:
            command = 'echo "KEY_${LLM_API_KEY:-GONE}_"; echo "benign_${RA_TEST_BENIGN}"'

        from research_assistant.tools.bash import run_bash

        out = asyncio.run(run_bash(command, cwd=str(tmp_path)))

        assert "sk-top-secret" not in out, f"密钥经 bash 泄露：{out!r}"
        assert "benign_visible" in out, "普通变量被误清"

    def test_bash_keeps_path_so_shell_still_works(self, tmp_path):
        """反向断言：净化不能清掉 PATH，否则连 shell 都找不到可执行文件。"""
        from research_assistant.tools.bash import run_bash

        out = asyncio.run(run_bash("echo alive", cwd=str(tmp_path)))
        assert "alive" in out, f"净化破坏了 PATH：{out!r}"


class TestFrozenExecEnvSanitized:
    """frozen_exec 的 spawn 子进程净化（G-4 收口）。

    ``multiprocessing.Process`` 不支持 env 参数，无法像 ``_run_process``
    那样在启动前换环境，只能由子进程在 exec 前自净。
    """

    def test_spawn_child_env_is_sanitized(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-top-secret")
        monkeypatch.setenv("RA_TEST_BENIGN", "visible")

        from research_assistant.tools.frozen_exec import run_python_inprocess

        code = (
            "import os\n"
            "keys = list(os.environ)\n"
            "print('LEAK' if 'LLM_API_KEY' in keys else 'CLEAN')\n"
            "print('BENIGN_' + os.environ.get('RA_TEST_BENIGN', 'missing'))\n"
        )
        out = asyncio.run(run_python_inprocess(code, cwd=str(tmp_path)))
        assert "CLEAN" in out, f"spawn 子进程仍有密钥：{out!r}"
        assert "BENIGN_visible" in out, "普通变量被误清"

    def test_spawn_child_keeps_home_so_matplotlib_works(self, tmp_path, monkeypatch):
        """红线（实现时踩过的坑）：必须**先取净化快照再 clear**。

        若先 clear 再调 sanitized_exec_env()，拿到的是空表——子进程只剩
        一个变量，matplotlib 因找不到 HOME/USERPROFILE 直接崩
        （实测 N=1 → RuntimeError: Could not determine home directory）。
        这里用"环境变量数量必须可观"锁住该回归。
        """
        from research_assistant.tools.frozen_exec import run_python_inprocess

        code = (
            "import os\n"
            "n = len(os.environ)\n"
            "print('HOME_OK' if (os.environ.get('HOME') or os.environ.get('USERPROFILE')) else 'HOME_MISSING')\n"
            "print('COUNT', n)\n"
        )
        out = asyncio.run(run_python_inprocess(code, cwd=str(tmp_path)))
        assert "HOME_OK" in out, f"HOME/USERPROFILE 丢失：{out!r}"
        # 空表意味着净化顺序反了；正常工作区环境至少几十个变量
        count = int(out.split("COUNT")[1].split()[0])
        assert count > 10, f"子进程环境近乎为空（N={count}）——clear 在快照之前执行"
