"""模型设置 API（R6 计划：图形化配置普通用户的入口）。

R8 起读写**全局配置** ``%APPDATA%/ResearchAssistant/.env``（跨工作区
共享——切换工作目录不丢配置），工作区 ``.env`` 降级为可选的按项目
覆盖层（``config.load_project_env`` 全局先行、工作区覆盖）。仅管理
LLM 四键：

    LLM_API_KEY / LLM_BASE_URL / LLM_MODEL / LLM_PROVIDER

约定：
- GET 返回的 api key 一律掩码（D2），其余三键为非敏感值原样返回供表单预填；
- POST 行式改写全局 ``.env``：已知键原地更新，用户手工添加的其它行/注释
  原样保留（D3），并同步 ``os.environ`` 使运行中的服务即刻生效（免重启）；
- 读写前先跑 ``config.ensure_global_config``：老版本把配置存在工作区
  ``.env`` 的，首次访问自动上移到全局（一次性、单向）；
- ``/test`` 用表单当前值临时建 client 发一次最小请求，**不落盘**（D4）。

路由不带 ``/api`` 前缀，由 app.py 以 ``prefix="/api"`` 挂载（与
workspace.py 同一惯例）。测试通过覆写 ``app.state.env_file`` 指向临时
文件来隔离；缺省回退 ``app.state.cwd/.env``。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..config import ensure_global_config, resolve_model

router = APIRouter()

#: 本模块托管的 .env 键（顺序即写入顺序）。
MANAGED_KEYS = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_PROVIDER")

#: /test 连接试探的超时秒数。
TEST_TIMEOUT_S = 30


class SettingsPayload(BaseModel):
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_provider: str = ""


def _env_path(request: Request) -> Path:
    """全局配置 .env（R8）；lifespan 赋值，测试可覆写，缺省回退工作区。"""
    override = getattr(request.app.state, "env_file", None)
    if override:
        return Path(override)
    return Path(getattr(request.app.state, "cwd", None) or Path.cwd()) / ".env"


def _read_managed(path: Path) -> dict[str, str]:
    """从 .env 行式解析托管键；缺失的键返回空串占位。"""
    values = {k: "" for k in MANAGED_KEYS}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        key = key.strip()
        if key in values:
            values[key] = val.strip().strip('"').strip("'")
    return values


def _mask(key: str) -> str:
    """掩码展示：保留首尾各 4 位，过短或为空则整体打码（D2）。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}***{key[-4:]}"


def _rewrite_env(path: Path, values: dict[str, str]) -> None:
    """行式改写：托管键原地更新（重复键只留第一处），其余行原样保留。"""
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        candidate = None
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in values:
                candidate = key
        if candidate and candidate not in seen:
            out.append(f"{candidate}={values[candidate]}")  # 首次出现：原地更新
            seen.add(candidate)
        elif candidate:
            pass  # 重复出现的托管键：丢弃（只留首处）
        else:
            out.append(line)  # 注释 / 无关键：原样保留

    for key in MANAGED_KEYS:  # 缺失的托管键按声明顺序补到末尾
        if key not in seen:
            out.append(f"{key}={values[key]}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _apply_environ(values: dict[str, str]) -> None:
    """保存后即刻生效：非空键写入 os.environ，空键移除（免重启）。"""
    for key in MANAGED_KEYS:
        if values[key]:
            os.environ[key] = values[key]
        else:
            os.environ.pop(key, None)


@router.get("/settings")
async def get_settings(request: Request):
    # 老配置一次性上移（幂等）：服务未重启也会在首次打开设置页时完成
    cwd = getattr(request.app.state, "cwd", None)
    if cwd:
        ensure_global_config(Path(cwd))
    values = _read_managed(_env_path(request))
    return {
        "configured": bool(values["LLM_API_KEY"]),
        "llm_api_key_masked": _mask(values["LLM_API_KEY"]),
        "llm_base_url": values["LLM_BASE_URL"],
        "llm_model": values["LLM_MODEL"],
        "llm_provider": values["LLM_PROVIDER"],
    }


@router.post("/settings")
async def save_settings(payload: SettingsPayload, request: Request):
    path = _env_path(request)
    api_key = payload.llm_api_key.strip()
    if not api_key:  # 空 Key = 沿用已配置值（出于安全 GET 只回掩码，不逼用户重输）
        api_key = _read_managed(path)["LLM_API_KEY"]
    if not api_key:
        raise HTTPException(status_code=422, detail="API Key 不能为空")
    values = {
        "LLM_API_KEY": api_key,
        "LLM_BASE_URL": payload.llm_base_url.strip(),
        "LLM_MODEL": payload.llm_model.strip(),
        "LLM_PROVIDER": payload.llm_provider.strip(),
    }
    _rewrite_env(path, values)
    _apply_environ(values)
    # 刷新 lifespan 快照，保证任何仍读 app.state.model 的消费方同步（R7 反馈 #2）
    request.app.state.model = resolve_model(None)
    return {
        "ok": True,
        "env_file": path.name,
        "llm_api_key_masked": _mask(api_key),
    }


@router.post("/settings/test")
async def test_settings(payload: SettingsPayload, request: Request):
    """用表单当前值试连一次，不落盘（D4）；Key 留空则用已配置的。"""
    api_key = payload.llm_api_key.strip()
    if not api_key:
        api_key = _read_managed(_env_path(request))["LLM_API_KEY"]
    model = payload.llm_model.strip()
    if not api_key:
        raise HTTPException(status_code=422, detail="请先填写 API Key")
    if not model:
        raise HTTPException(status_code=422, detail="请先填写模型名称")

    from ..llm.factory import create_llm_client

    client = create_llm_client(
        api_key=api_key,
        base_url=payload.llm_base_url.strip() or None,
        model=model,
        provider=payload.llm_provider.strip() or None,
    )
    # R9：带 on_chunk 探测 → 走 stream:true 分支，与会话真实路径对称。
    # 旧实现测的是非流式——不少网关对流式表现不同（缓冲不出/挂起），
    # 出现过「测试连接通过、会话却永久思考中」的错位。
    chunks: list[str] = []

    def _probe_chunk(delta: str) -> None:
        if delta:
            chunks.append(delta)

    try:
        resp = await asyncio.wait_for(
            client.chat([{"role": "user", "content": "请只回复两个字：正常"}],
                        max_tokens=32, on_chunk=_probe_chunk),
            timeout=TEST_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "error": f"连接超时（{TEST_TIMEOUT_S}s）——端点不可达或流式无响应；"
                    "请核对 Base URL 与网络连通性",
        }
    except Exception as exc:  # 网络/鉴权/模型名错误等，原文透传给前端
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        await client.close()

    reply = (resp.content or "") or "".join(chunks)
    return {"ok": True, "model": model, "reply": reply[:60]}
