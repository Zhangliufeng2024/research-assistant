"""Configuration helpers for research assistant.

Centralizes environment loading, model selection, and LLM client creation.
No SDK dependencies — uses the custom llm/ abstraction.
"""

import os
import re
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .constants import DEFAULT_ANTHROPIC_MODEL
from .core import load_system_instructions
from .llm.base import LLMClient
from .llm.factory import create_llm_client


def generate_session_dir_name(query: str) -> str:
    """Generate a timestamped directory name from a query string."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-zA-Z0-9]", "_", query.strip()[:40].lower()).strip("_")
    return f"{timestamp}_{slug}"


def build_system_instructions(work_dir: Path, target_dir_name: str) -> str:
    """Load WRITER.md and append working-directory instructions."""
    instructions = load_system_instructions(work_dir)
    instructions += f"""

IMPORTANT - WORKING DIRECTORY:
- Your working directory is: {work_dir}
- ALWAYS create files in this EXACT unique session directory: {work_dir / "writing_outputs" / target_dir_name}/
- NEVER create your own timestamped directories; USE the one provided above.
- NEVER write to /tmp/ or any other directory.
- For all papers, reports, or research summaries, the root output folder is: writing_outputs/{target_dir_name}/
"""
    return instructions


def app_data_dir() -> Path:
    """应用级数据目录（跨工作区共享）：Windows 用 %APPDATA%/ResearchAssistant，
    其它平台回退 ~/.research-assistant。桌面壳的工作区记忆也放在这里。"""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".research-assistant"
    return base / "ResearchAssistant"


def app_config_env_path() -> Path:
    """全局配置 .env：设置页写入这里，所有工作区共享一份模型接入配置。"""
    return app_data_dir() / ".env"


def load_project_env(work_dir: Path) -> None:
    """加载配置：全局 .env 先行（底层），工作区 .env 后行（覆盖层）。

    设置页把模型接入写到全局文件——切换工作目录不丢配置（R8 反馈 #1 的
    配套改造）；工作区 .env 仍可按项目覆盖个别键（与 CLI 用法兼容）。
    """
    for env_file in (app_config_env_path(), work_dir / ".env"):
        if env_file.exists():
            load_dotenv(dotenv_path=env_file, override=True)

    for key in (
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_PROVIDER",
    ):
        val = os.getenv(key)
        if val is not None:
            os.environ[key] = val


#: 设置页托管、参与「工作区 → 全局」一次性上移的键（R8：老用户配置上迁）。
_MANAGED_LLM_KEYS = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_PROVIDER")


def ensure_global_config(workspace: Path | None = None) -> Path:
    """把工作区 .env 里的 LLM 四键上移到全局配置（一次性、单向、幂等）。

    仅当全局文件尚未配置 LLM_API_KEY 而工作区已配置时触发——覆盖
    v3.3.0 及更早「配置存工作区 .env」的老用户：首次启动/打开设置页即
    自动上移，之后以全局文件为准。绝不覆盖全局已有的任何值。
    """
    global_path = app_config_env_path()
    try:
        workspace = Path(workspace) if workspace else Path.cwd()
        ws_file = workspace / ".env"

        def _read(path: Path) -> dict[str, str]:
            values: dict[str, str] = {}
            if not path.exists():
                return values
            for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    values[k.strip()] = v.strip().strip('"').strip("'")
            return values

        global_values = _read(global_path)
        if global_values.get("LLM_API_KEY"):
            return global_path  # 全局已配置：不动
        ws_values = _read(ws_file)
        pairs = [(k, ws_values[k]) for k in _MANAGED_LLM_KEYS if ws_values.get(k)]
        if not pairs:
            return global_path  # 工作区也没配置：无事可做

        lines = []
        if global_path.exists():
            lines = global_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if lines and lines[-1].strip():
                lines.append("")
        lines.append("# 上移自工作区 .env（R8：配置全局共享，切换工作目录不丢）")
        lines.extend(f"{k}={v}" for k, v in pairs)
        global_path.parent.mkdir(parents=True, exist_ok=True)
        global_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass  # 迁移失败不阻断启动；设置页保存仍会写全局文件
    return global_path


def resolve_model(model: str | None = None) -> str:
    """Return the writing model. Priority: explicit param -> env -> default."""
    if model:
        return model
    return os.getenv("LLM_MODEL") or DEFAULT_ANTHROPIC_MODEL


def build_llm_client(
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    provider: str | None = None,
) -> LLMClient:
    """Create an LLM client from config."""
    mdl = resolve_model(model)
    return create_llm_client(
        api_key=api_key,
        base_url=base_url,
        model=mdl,
        provider=provider,
    )
