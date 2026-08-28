"""模型与运行配置 API（R6 图形化配置入口；A2 扩展为全量设置页后端）。

R8 起读写**全局配置** ``%APPDATA%/ResearchAssistant/.env``（跨工作区
共享——切换工作目录不丢配置），工作区 ``.env`` 降级为可选的按项目
覆盖层（``config.load_project_env`` 全局先行、工作区覆盖）。

托管键分两组（A2）：
- ``MANAGED_KEYS``：LLM 接入四键 + PARALLEL_API_KEY / IMAGE_API_KEY。
  凡 ``*_API_KEY`` 一律掩码展示，表单留空 = 沿用已配置值；
- ``EXTENDED_KEYS``：带类型/取值约束的运行键（图像端点、预算上限、
  请求节奏、审批与权限模式）。数值键在保存时做范围校验，非法值返回
  400 + 中文错误，且**先整体校验、后落盘**——一个非法值不会让其它
  合法键先写进 .env。

约定：
- GET 返回的密钥一律掩码（D2），其余键原样/解析后返回供表单预填；
- POST/PUT 行式改写全局 ``.env``：已知键原地更新，用户手工添加的其它
  行/注释原样保留（D3），并同步 ``os.environ`` 使运行中的服务即刻生效
  （免重启）；扩展键 payload 未携带 = 本次不动——老客户端只发 LLM 四
  键不会意外清掉扩展配置；显式空串 = 清除该键；
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

#: 本模块托管的 .env 键：LLM 接入 + 联网检索 / 图像生成的密钥（顺序即写入顺序）。
MANAGED_KEYS = (
    "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_PROVIDER",
    "PARALLEL_API_KEY", "IMAGE_API_KEY",
)

# A2 扩展键：类型与约束。number 键按 min / min_exclusive 校验（int=True 还要求
# 整数）；choice 键枚举合法值——取值与代码里的实际判断逻辑对齐：
#   RA_APPROVAL_MODE   cli.py 只认 "interactive"（其余一律视为关闭）
#   RA_PERMISSION_MODE tools/permissions.py 只认 "off" / "deny_dangerous"
EXTENDED_KEYS: dict[str, dict] = {
    "IMAGE_BASE_URL": {"type": "str"},
    "IMAGE_MODEL": {"type": "str"},
    "RA_MAX_COST_USD": {
        "type": "number", "min_exclusive": 0,
        "error": "成本预算上限必须大于 0（单位：美元）",
    },
    "RA_MAX_TOKENS": {
        "type": "number", "min": 1, "int": True,
        "error": "Token 总量上限必须是不小于 1 的整数",
    },
    "RA_MAX_TURNS": {
        "type": "number", "min": 1, "int": True,
        "error": "轮次上限必须是不小于 1 的整数",
    },
    # 方案 5：RA_MAX_* 预算族最后一个缺口——墙钟时长上限（budget.py 从 env
    # 读取但此前设置页无处可配）。<=0/留空 = 不限，与 BudgetLimits 语义一致。
    "RA_MAX_WALL_SECONDS": {
        "type": "number", "min_exclusive": 0,
        "error": "墙钟时长上限必须大于 0（单位：秒；留空 = 不限制）",
    },
    "LLM_REQUEST_INTERVAL": {
        "type": "number", "min": 0,
        "error": "请求间隔不能为负数（单位：秒）",
    },
    "RA_LLM_FIRST_BYTE_TIMEOUT": {
        "type": "number", "min": 5,
        "error": "首字节超时不能小于 5 秒",
    },
    "RA_APPROVAL_MODE": {"type": "choice", "choices": ("off", "interactive")},
    "RA_PERMISSION_MODE": {"type": "choice", "choices": ("deny_dangerous", "off")},
}

#: 托管 + 扩展的全集（读取/落盘/环境变量同步都以此为准）。
ALL_KEYS: tuple[str, ...] = MANAGED_KEYS + tuple(EXTENDED_KEYS)

#: /test 连接试探的超时秒数。
TEST_TIMEOUT_S = 30


def _is_secret(key: str) -> bool:
    """掩码规则只作用于 *_API_KEY；其余键明文返回供表单预填。"""
    return key.endswith("_API_KEY")


class SettingsPayload(BaseModel):
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_provider: str = ""
    # —— A2 扩展键：全部可选。None（payload 未携带）= 本次不动该键；
    # 显式空串 = 清除。两个 API Key 字段例外：空串同样表示「沿用已配置
    # 值」，与 LLM_API_KEY 的既有契约一致（GET 不回明文，无法回填空值语义）。
    parallel_api_key: str | None = None
    image_api_key: str | None = None
    image_base_url: str | None = None
    image_model: str | None = None
    # 数值字段声明为 float | str：JSON 数字与字符串都收（宽松对接各类客户端）
    ra_max_cost_usd: float | str | None = None
    ra_max_tokens: float | str | None = None
    ra_max_turns: float | str | None = None
    ra_max_wall_seconds: float | str | None = None
    llm_request_interval: float | str | None = None
    ra_llm_first_byte_timeout: float | str | None = None
    ra_approval_mode: str | None = None
    ra_permission_mode: str | None = None


def _env_path(request: Request) -> Path:
    """全局配置 .env（R8）；lifespan 赋值，测试可覆写，缺省回退工作区。"""
    override = getattr(request.app.state, "env_file", None)
    if override:
        return Path(override)
    return Path(getattr(request.app.state, "cwd", None) or Path.cwd()) / ".env"


def _read_managed(path: Path) -> dict[str, str]:
    """从 .env 行式解析全部托管/扩展键；缺失的键返回空串占位。"""
    values = {k: "" for k in ALL_KEYS}
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


def _normalize_extended(key: str, raw) -> str:
    """校验扩展键新值并归一化为 .env 存储串；非法值抛 ValueError（中文）。"""
    spec = EXTENDED_KEYS[key]
    text = "" if raw is None else str(raw).strip()
    if not text:  # 显式空串 = 清除该键（在 choice/number 校验之前短路）
        return ""
    if spec["type"] == "choice":
        val = text.lower()
        if val not in spec["choices"]:
            raise ValueError(f"{key} 仅支持 {' / '.join(spec['choices'])}")
        return val
    if spec["type"] == "number":
        try:
            num = float(text)
        except ValueError:
            raise ValueError(f"{key} 必须是数字") from None
        if spec.get("int"):
            if not float(num).is_integer():
                raise ValueError(spec["error"])
            num = int(num)
        lo_min, lo_excl = spec.get("min"), spec.get("min_exclusive")
        if (lo_min is not None and num < lo_min) or (
            lo_excl is not None and num <= lo_excl
        ):
            raise ValueError(spec["error"])
        return str(num)
    return text  # str 型：原样（已 strip）


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

    # 缺失的扩展键只在「确有非空值」时追加：避免一次保存给 .env 塞进
    # 一屏 `KEY=` 空行（未配置的运行键保持缺省即走 constants 默认值）。
    for key in EXTENDED_KEYS:
        if key not in seen and values[key]:
            out.append(f"{key}={values[key]}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _apply_environ(values: dict[str, str]) -> None:
    """保存后即刻生效：非空键写入 os.environ，空键移除（免重启）。"""
    for key in ALL_KEYS:
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

    def _field(key: str):
        raw = values[key]
        if _is_secret(key):
            return _mask(raw)
        spec = EXTENDED_KEYS.get(key)
        if spec and spec["type"] == "number" and raw:
            try:
                num = float(raw)
            except ValueError:
                return None  # 手工改坏 .env 时前端显示留空，不让页面炸掉
            return int(num) if num.is_integer() else num
        return raw

    body = {"configured": bool(values["LLM_API_KEY"])}
    body.update({_snake(k): _field(k) for k in ALL_KEYS})
    return body


def _snake(env_key: str) -> str:
    """ENV_KEY → 响应字段名；掩码键追加 _masked 后缀（沿用 D2 命名惯例）。"""
    name = env_key.lower()
    return f"{name}_masked" if _is_secret(env_key) else name


@router.api_route("/settings", methods=["POST", "PUT"])
async def save_settings(payload: SettingsPayload, request: Request):
    path = _env_path(request)
    current = _read_managed(path)

    def _secret_or_keep(new: str | None, env_key: str) -> str:
        # 空 Key = 沿用已配置值（出于安全 GET 只回掩码，不逼用户重输）
        return (new or "").strip() or current[env_key]

    api_key = _secret_or_keep(payload.llm_api_key, "LLM_API_KEY")
    if not api_key:
        raise HTTPException(status_code=422, detail="API Key 不能为空")

    # 先整体校验扩展键、全部通过后才动文件：一个非法值不应让前面已
    # 合法的键先落盘（半写状态比拒绝更难排查）。
    updates: dict[str, str] = {}
    for field_name, env_key in ((k.lower(), k) for k in EXTENDED_KEYS):
        raw = getattr(payload, field_name)
        if raw is None:  # 未携带 = 本次不动
            continue
        try:
            updates[env_key] = _normalize_extended(env_key, raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    values = {k: current[k] for k in ALL_KEYS}
    values.update({
        "LLM_API_KEY": api_key,
        "LLM_BASE_URL": payload.llm_base_url.strip(),
        "LLM_MODEL": payload.llm_model.strip(),
        "LLM_PROVIDER": payload.llm_provider.strip(),
        "PARALLEL_API_KEY": _secret_or_keep(payload.parallel_api_key, "PARALLEL_API_KEY"),
        "IMAGE_API_KEY": _secret_or_keep(payload.image_api_key, "IMAGE_API_KEY"),
    })
    values.update(updates)

    _rewrite_env(path, values)
    _apply_environ(values)
    # 刷新 lifespan 快照，保证任何仍读 app.state.model 的消费方同步（R7 反馈 #2）
    request.app.state.model = resolve_model(None)
    return {
        "ok": True,
        "env_file": path.name,
        "llm_api_key_masked": _mask(api_key),
        "parallel_api_key_masked": _mask(values["PARALLEL_API_KEY"]),
        "image_api_key_masked": _mask(values["IMAGE_API_KEY"]),
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
