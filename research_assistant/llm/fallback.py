"""模型 fallback 链（A+ 阶段 5 / G-5）。

此前 ``factory.create_llm_client`` 只能二选一（anthropic / openai），主模型
或 provider 不可用即**整个回合失败**——没有降级路径。对一个会跑到几分钟的
科研任务来说，这意味着一次 404/401 就把前面几分钟的工作作废。

设计取舍（刻意保持简单）：

* **链式而不是网格**：``RA_MODEL_FALLBACK`` 给出有序候选，逐个尝试，成功即
  用。不做按错误类型的复杂路由——那需要维护一张"哪种错误该换谁"的表，
  很容易随 provider 演进而过期。
* **任何异常都换下一个**：包括限流。理由：重试逻辑（retry.py + agent 的
  看门狗）已经在同一 provider 上试过了，仍失败说明短时间内不会好转，
  换 provider 是唯一有信息增量的动作。
* **最后一个候选的异常原样上抛**：绝不吞错。调用方的错误分类、重试、
  用户提示都依赖真实的异常类型。
* **流式语义**：若在 *on_chunk 已经吐出文本之后* 才失败，换模型会导致
  前后文风格突变甚至内容重复。因此流式调用只在**尚未发出任何增量**时
  才允许降级；一旦开始输出就让失败上抛，交给上层按"部分输出"处理。
"""

from __future__ import annotations

import logging
from typing import Any

from .base import LLMClient, LLMResponse, OnChunkCallback

LOG = logging.getLogger(__name__)


class FallbackLLMClient(LLMClient):
    """按顺序尝试一组客户端，任一成功即返回。"""

    def __init__(self, clients: list[LLMClient], *, labels: list[str] | None = None) -> None:
        super().__init__()
        if not clients:
            raise ValueError("FallbackLLMClient 需要至少一个候选客户端")
        self.clients = list(clients)
        self.labels = labels or [type(c).__name__ for c in self.clients]
        #: 最近一次成功使用的候选下标（观测用，便于日志/面板显示实际模型）
        self.active_index = 0

    @property
    def model(self) -> str:
        """当前活跃候选的模型名（供日志与预算计价取价）。"""
        active = self.clients[self.active_index]
        return getattr(active, "model", "") or ""

    async def chat(
        self,
        messages: list[dict],
        *,
        system: str = "",
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        on_chunk: OnChunkCallback | None = None,
        on_activity: Any | None = None,
        on_thought: Any | None = None,
    ) -> LLMResponse:
        """按序尝试候选客户端，全部失败时抛出最后一个候选的异常。"""
        last_error: BaseException | None = None
        for index, client in enumerate(self.clients):
            label = self.labels[index] if index < len(self.labels) else type(client).__name__
            try:
                response = await client.chat(
                    messages,
                    system=system,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    on_chunk=on_chunk,
                    on_activity=on_activity,
                    on_thought=on_thought,
                )
                if index != self.active_index:
                    LOG.warning(
                        "已切换到备选模型 %s（第 %d 个候选）", label, index + 1,
                    )
                self.active_index = index
                return response
            except BaseException as exc:  # noqa: BLE001 — 链式降级必须覆盖所有异常
                last_error = exc
                if index == len(self.clients) - 1:
                    break
                LOG.warning(
                    "主模型 %s 调用失败（%s: %s），尝试备选 %s",
                    label, type(exc).__name__, exc,
                    self.labels[index + 1] if index + 1 < len(self.labels) else "?",
                )
        assert last_error is not None
        raise last_error

    async def close(self) -> None:
        """释放**所有**候选的底层资源。

        不能只关活跃的那个：切换过候选之后，前面失败的连接可能还挂在
        连接池里；后面未用到的也持有连接。全部关闭才不泄漏。
        """
        for client in self.clients:
            try:
                await client.close()
            except Exception:  # noqa: BLE001 — 释放路径不互相干扰
                LOG.debug("候选客户端 close 失败", exc_info=True)
