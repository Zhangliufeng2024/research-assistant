"""SQLite-backed platform state.

The filesystem remains the source of truth for research artifacts.  This store
owns the relational state that does not fit safely in a WebSocket connection:
projects, background tasks, and their ordered event streams.

域拆分（工程债，2026-08-31）：任务 / 科研对象 / 队列三个域的方法分别位于
``runtime/store_tasks.py``、``store_research.py``、``store_queue.py``，公共
连接与解码设施在 ``store_base.py``；本文件退化为组合门面，公共 API 不变。
"""

from __future__ import annotations

from .platform_schema import PROJECT_OS_VERSION, SCHEMA_VERSION, initialize_schema  # noqa: F401
from .store_base import StoreBase
from .store_queue import QueueMixin
from .store_research import ResearchMixin
from .store_tasks import TaskMixin


class PlatformStore(TaskMixin, ResearchMixin, QueueMixin, StoreBase):
    """Small transactional repository built on the Python stdlib SQLite driver."""

    pass
