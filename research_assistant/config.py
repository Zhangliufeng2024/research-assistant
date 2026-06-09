"""Configuration helpers for research assistant.

Centralizes environment loading, model selection, and LLM client creation.
No SDK dependencies — uses the custom llm/ abstraction.
"""

import os
import re
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

from .core import load_system_instructions
from .llm.factory import create_llm_client
from .llm.base import LLMClient
from .constants import DEFAULT_ANTHROPIC_MODEL


def generate_session_dir_name(query: str) -> str:
    """Generate a timestamped directory name from a query string."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r'[^a-zA-Z0-9]', '_', query.strip()[:40].lower()).strip('_')
    return f"{timestamp}_{slug}"


def build_system_instructions(work_dir: Path, target_dir_name: str) -> str:
    """Load WRITER.md and append working-directory instructions."""
    instructions = load_system_instructions(work_dir)
    instructions += f"""

IMPORTANT - WORKING DIRECTORY:
- Your working directory is: {work_dir}
- ALWAYS create files in this EXACT unique session directory: {work_dir / 'writing_outputs' / target_dir_name}/
- NEVER create your own timestamped directories; USE the one provided above.
- NEVER write to /tmp/ or any other directory.
- For all papers, reports, or research summaries, the root output folder is: writing_outputs/{target_dir_name}/
"""
    return instructions


def load_project_env(work_dir: Path) -> None:
    """Load .env from work_dir and force project-scoped vars into os.environ."""
    env_file = work_dir / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=True)

    for key in (
        "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_PROVIDER",
    ):
        val = os.getenv(key)
        if val is not None:
            os.environ[key] = val


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
