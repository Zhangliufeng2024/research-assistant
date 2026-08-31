"""Stable run-directory allocation shared by all background task hosts.

工程债：``web/ws.py`` 与 ``runtime/scheduler_dispatcher.py`` 各有一份逐字
相同的 ``_allocate_output_dir``——同一语义两份实现，改一处漏一处。收敛到
本模块，两个宿主各自 ``as _allocate_output_dir`` 别名引用。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from ..config import generate_session_dir_name


def allocate_output_dir(cwd: Path, query: str) -> Path:
    """Allocate a stable run directory before the generator starts.

    Durable task rows must know their artifact root even if the process dies
    before the first progress frame.  The short random suffix only handles
    two launches in the same second; normal UI names remain timestamped.
    """
    root = cwd / "writing_outputs"
    root.mkdir(parents=True, exist_ok=True)
    base = generate_session_dir_name(query)
    candidate = root / base
    try:
        candidate.mkdir()
    except FileExistsError:
        candidate = root / f"{base}_{uuid.uuid4().hex[:6]}"
        candidate.mkdir()
    return candidate
