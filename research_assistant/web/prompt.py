"""提示词增强 API —— 把用户的粗略指令扩写成结构化研究提示词。

设计要点：

- **一次性、无副作用**：不落盘、不进会话历史、不消耗任务预算；只在用户
  点「增强」时发一次最小请求，结果回填到输入框由用户确认后再发送。
- **与会话同路径**：沿用 ``settings.py:/settings/test`` 的调用范式
  （``create_llm_client`` + 流式探测 + ``asyncio.wait_for`` + ``finally
  close``）。R9 的教训是：非流式探测会掩盖网关的流式异常，出现「测试
  通过、会话挂起」的错位，因此这里同样带 ``on_chunk`` 走 stream 分支。
- **失败可降级**：模型未配置 / 超时 / 鉴权失败一律返回 ``ok:false`` +
  中文 ``error``，前端保持原文不变并 toast 提示——**绝不静默吞异常，也
  绝不把用户写好的话弄丢**。

路由不带 ``/api`` 前缀，由 app.py 以 ``prefix="/api"`` 挂载（与
settings.py、workspace.py 同一惯例）。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import resolve_model
from ..core import get_api_key

router = APIRouter()

#: 增强请求的超时秒数（比连通性试探宽松：这是一次真实的短生成）。
ENHANCE_TIMEOUT_S = 45

#: 输入上限：超过此长度直接拒绝，避免把整篇草稿塞进扩写请求。
MAX_INPUT_CHARS = 4000

#: 扩写结果上限（token）。够写一份结构化提示词，又不会跑飞。
MAX_OUTPUT_TOKENS = 1200

#: 系统提示：只做「提示词工程」，不做「回答问题」。
_SYSTEM_PROMPT = """你是一名科研提示词工程师，服务于一个土木/环境/能源/AI 交叉领域的
AI 研究助手。用户会给你一段**粗糙的研究指令**（可能是残缺的中文短句），
你的任务是把它改写为一份**结构化、可直接执行**的研究提示词。

硬性要求：
1. **只输出改写后的提示词本身**，不要任何前言、解释、引号包裹或 Markdown
   代码块围栏（```），不要说「好的，这是改写后的版本」。
2. **保持用户的原始意图与语言**（用户用中文提问就输出中文）。不要臆造
   用户没提到的研究对象、数据、结论或引用文献。
3. 补全执行所需的维度，按实际需要选用（不必全用，不要生硬堆砌）：
   - 研究目标与待回答的核心问题
   - 输出物类型（论文 / 综述 / 报告 / 基金申请书 / 实验方案 / 数据分析）
   - 目标期刊或场合（若用户未指定，不要编造具体期刊名）
   - 结构要求（章节安排、字数或篇幅）
   - 方法与数据（如需计算，说明工具或公式来源）
   - 引用与格式要求（真实可核查的文献，禁占位引用）
   - 图表要求（需要的图/表类型与数量）
4. 输出用**简洁的条列结构**，一条一行，便于用户直接删改。控制在 400 字
   以内——是「可编辑的骨架」，不是长篇大论。
5. 若用户的指令已经足够清晰具体，只需做最小增强（补上明显缺失的执行
   维度），不要为了显得专业而注水膨胀。"""


class EnhancePayload(BaseModel):
    text: str = Field(default="", description="待增强的原始指令")


@router.post("/prompt/enhance")
async def enhance_prompt(payload: EnhancePayload, request: Request):
    """把粗略指令扩写成结构化提示词；失败返回 ok:false + 中文原因。"""
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="请先输入内容再增强")
    if len(text) > MAX_INPUT_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"内容过长（>{MAX_INPUT_CHARS} 字符），请精简后再增强",
        )

    # get_api_key() 未配置时抛 ValueError（core.py:181），不是返回空串
    try:
        api_key = get_api_key()
    except ValueError:
        # 不抛 500：模型未配置是用户可自行修复的状态，交给前端 toast 引导
        return {
            "ok": False,
            "error": "尚未配置模型 API Key，请先在「设置」页完成配置",
        }

    # resolve_model() 恒返回非空（缺省回落内置默认模型），无需判空
    model = getattr(request.app.state, "model", None) or resolve_model(None)

    from ..llm.factory import create_llm_client

    client = create_llm_client(api_key=api_key, model=model)
    chunks: list[str] = []

    def _collect(delta: str) -> None:
        if delta:
            chunks.append(delta)

    try:
        resp = await asyncio.wait_for(
            client.chat(
                [{"role": "user", "content": text}],
                system=_SYSTEM_PROMPT,
                max_tokens=MAX_OUTPUT_TOKENS,
                on_chunk=_collect,
            ),
            timeout=ENHANCE_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "error": f"增强超时（{ENHANCE_TIMEOUT_S}s）——模型响应过慢，请重试或精简输入",
        }
    except Exception as exc:
        # 网络/鉴权/模型名错误等：原文透传（截断）供前端展示
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        await client.close()

    enhanced = (resp.content or "").strip() or "".join(chunks).strip()
    if not enhanced:
        return {"ok": False, "error": "模型返回为空，请重试（未改动您的原文）"}

    return {"ok": True, "enhanced": enhanced, "model": model}
