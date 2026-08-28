"""Configuration helpers for research assistant.

Centralizes environment loading, model selection, and LLM client creation.
No SDK dependencies — uses the custom llm/ abstraction.
"""

import os
import re
import secrets
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .constants import DEFAULT_ANTHROPIC_MODEL
from .core import execution_contract_addendum, load_system_instructions
from .llm.base import LLMClient
from .llm.factory import create_llm_client


def generate_session_dir_name(query: str) -> str:
    """Generate a timestamped directory name from a query string.

    R17：加 6 位随机后缀根治秒级并发撞名（生日界：同秒千级创建才有个位数
    碰撞概率）；slug 保留 CJK 字符（中文查询不再退化为纯时间戳目录）。
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(
        r"[^a-zA-Z0-9一-鿿]", "_", query.strip()[:40].lower(),
    ).strip("_")
    rand6 = f"{secrets.randbelow(16**6):06x}"
    if slug:
        return f"{timestamp}_{slug}_{rand6}"
    return f"{timestamp}_{rand6}"


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
    # R12 P1：打包态执行契约（bash 禁 python / run_python / run_script / WS）
    instructions += execution_contract_addendum()
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


#: 设置页托管、参与「工作区 → 全局」一次性上移的键（R8：老用户配置上迁）。
_MANAGED_LLM_KEYS = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_PROVIDER")


def _read_env_file(path: Path) -> dict[str, str]:
    """极简 .env 键值解析（不展开引号内 #、不处理 export 前缀）。"""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def load_project_env(work_dir: Path) -> None:
    """加载配置：全局 .env 先行（底层），工作区 .env 后行（覆盖层）。

    缺陷 G：托管四键以**全局文件为终局裁决**——设置页写入的新值不再被
    工作区残留的旧 Key 压掉（全局文件里非空的托管键强制生效）；非托管键
    行为不变，仍是工作区覆盖层获胜。
    """
    global_path = app_config_env_path()
    for env_file in (global_path, work_dir / ".env"):
        if env_file.exists():
            load_dotenv(dotenv_path=env_file, override=True)

    # 托管键终局裁决：全局 > 工作区覆盖层（空值视为未配置，不强制）
    global_values = _read_env_file(global_path)
    for key in _MANAGED_LLM_KEYS:
        value = global_values.get(key)
        if value:
            os.environ[key] = value


def _retire_workspace_managed_keys(ws_file: Path, keys: tuple[str, ...]) -> None:
    """迁移成功后移除工作区 .env 中已上移的托管键行（先备份一份）。

    残留是「旧 Key 复活」的根源：不清源的话，下次 load_project_env 时
    工作区覆盖层会把失效的 Key 再次压进环境。备份 ``.env.ra-migration.bak``
    仅在首次清理时创建，绝不覆盖已有备份。
    """
    if not ws_file.exists() or not keys:
        return
    lines = ws_file.read_text(encoding="utf-8", errors="replace").splitlines()

    def _is_managed(line: str) -> bool:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            return False
        return stripped.partition("=")[0].strip() in keys

    kept = [line for line in lines if not _is_managed(line)]
    if len(kept) == len(lines):
        return  # 没有托管键残留：不动文件、不留备份
    backup = ws_file.parent / ".env.ra-migration.bak"
    if not backup.exists():
        backup.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ws_file.write_text(
        "\n".join(kept) + ("\n" if kept else ""), encoding="utf-8",
    )


def ensure_global_config(workspace: Path | None = None) -> Path:
    """把工作区 .env 里的 LLM 四键上移到全局配置（一次性、单向、幂等）。

    仅当全局文件尚未配置 LLM_API_KEY 而工作区已配置时触发——覆盖
    v3.3.0 及更早「配置存工作区 .env」的老用户：首次启动/打开设置页即
    自动上移，之后以全局文件为准。绝不覆盖全局已有的任何值。
    上移成功后会清掉工作区的这四键（先备份），杜绝残留复活（缺陷 G）。
    """
    global_path = app_config_env_path()
    try:
        workspace = Path(workspace) if workspace else Path.cwd()
        ws_file = workspace / ".env"

        global_values = _read_env_file(global_path)
        if global_values.get("LLM_API_KEY"):
            return global_path  # 全局已配置：不动
        ws_values = _read_env_file(ws_file)
        migrated_keys = tuple(k for k in _MANAGED_LLM_KEYS if ws_values.get(k))
        pairs = [(k, ws_values[k]) for k in migrated_keys]
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

        # 上移成功 → 清除工作区残留（缺陷 G 第 2 步；OSError 由外层吞掉）
        _retire_workspace_managed_keys(ws_file, migrated_keys)
    except OSError:
        pass  # 迁移失败不阻断启动；设置页保存仍会写全局文件
    return global_path


def resolve_model(model: str | None = None) -> str:
    """Return the writing model. Priority: explicit param -> env -> default."""
    if model:
        return model
    return os.getenv("LLM_MODEL") or DEFAULT_ANTHROPIC_MODEL


def feature_flag(name: str, default: bool = False) -> bool:
    """统一 feature flag 读取（R17 重构灰度用）。

    环境变量命名 ``RA_FF_<NAME>``（name 传大写短名即可，如 ``"CHAT_TASK_LINK"``
    → ``RA_FF_CHAT_TASK_LINK``）。值 ``1/true/yes/on`` 视为开启；未设置时
    返回 ``default``。所有破坏性/行为变化型重构都必须挂 flag，先灰度后默认。
    """
    raw = os.getenv(f"RA_FF_{name.upper()}")
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def research_os_enabled() -> bool:
    """Feature flag for the unified research workspace.

    Enabled by default for new builds; setting ``RA_RESEARCH_OS=0`` keeps the
    legacy navigation available while a project is being migrated.
    """
    return (os.getenv("RA_RESEARCH_OS") or "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


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
