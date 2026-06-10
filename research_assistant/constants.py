"""Centralized constants for research assistant.

All magic numbers and configurable defaults live here to avoid
scattering them across the codebase.
"""

# ---------------------------------------------------------------------------
# HTTP / LLM
# ---------------------------------------------------------------------------
HTTP_TIMEOUT_SECONDS: float = 300.0
HTTP_CONNECT_TIMEOUT_SECONDS: float = 30.0
DEFAULT_LLM_REQUEST_INTERVAL: float = 2.0
DEFAULT_ANTHROPIC_MODEL: str = "claude-sonnet-4-6"
DEFAULT_OPENAI_MODEL: str = "gpt-4o"
ANTHROPIC_API_VERSION: str = "2023-06-01"

# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
DEFAULT_MAX_TURNS: int = 200
DEFAULT_MAX_CONTINUATIONS: int = 10
DEFAULT_TEMPERATURE: float = 0.5
DEFAULT_MAX_TOKENS: int = 16384
TASK_COMPLETE_MARKER: str = "[TASK_COMPLETE]"

# ---------------------------------------------------------------------------
# Retry / heartbeat
# ---------------------------------------------------------------------------
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_RETRY_BASE_DELAY: float = 5.0
DEFAULT_HEARTBEAT_TIMEOUT: float = 300.0

# ---------------------------------------------------------------------------
# Tool output limits
# ---------------------------------------------------------------------------
OUTPUT_TRUNCATION_LIMIT: int = 30_000
OUTPUT_TRUNCATION_HALF: int = 15_000

GREP_MAX_RESULTS: int = 200
GLOB_MAX_RESULTS: int = 500

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
DISPLAY_TRUNCATION_LENGTH: int = 60
DISPLAY_TOKEN_THRESHOLD: int = 1000

# ---------------------------------------------------------------------------
# File extensions (immutable sets)
# ---------------------------------------------------------------------------
IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    '.png', '.jpg', '.jpeg', '.gif', '.bmp',
    '.tiff', '.tif', '.svg', '.webp', '.ico',
})

MANUSCRIPT_EXTENSIONS: frozenset[str] = frozenset({'.tex'})

SOURCE_EXTENSIONS: frozenset[str] = frozenset({'.md', '.docx', '.pdf'})

DATA_EXTENSIONS: frozenset[str] = frozenset({
    '.csv', '.json', '.txt', '.xlsx', '.xls',
    '.tsv', '.xml', '.yaml', '.yml', '.sql',
})

BINARY_EXTENSIONS: frozenset[str] = frozenset({
    '.pyc', '.pyo', '.so', '.dll', '.exe', '.bin',
    '.png', '.jpg', '.pdf', '.zip',
})

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
DEFAULT_MAX_PARALLEL_RESEARCH: int = 4
DEFAULT_MAX_PARALLEL_FIGURES: int = 4
OUTPUT_SUBDIRS: tuple[str, ...] = (
    "drafts", "final", "references", "figures", "data", "sources",
)
