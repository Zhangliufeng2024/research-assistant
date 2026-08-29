"""Centralized constants for research assistant.

All magic numbers and configurable defaults live here to avoid
scattering them across the codebase.
"""

# ---------------------------------------------------------------------------
# HTTP / LLM
# ---------------------------------------------------------------------------
HTTP_TIMEOUT_SECONDS: float = 300.0
# 连接建立 15s 足够：被墙/填错端点应快失败（R9 前是 30s，叠加重试退避用户要
# 干等两分多钟才见到错误帧——表现为永久「思考中」）。
HTTP_CONNECT_TIMEOUT_SECONDS: float = 15.0
DEFAULT_LLM_REQUEST_INTERVAL: float = 2.0
# Claude 5 代系的有效别名（claude-sonnet-4-6 并非有效模型 ID，新装用户
# 只填 key 不填模型名会首报错）。
DEFAULT_ANTHROPIC_MODEL: str = "claude-sonnet-5"
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
# R9 反馈「永久思考中」治理：流式首字节前的静默窗口（连接+TLS+排队期没有任何
# on_activity 心跳）单独用短超时快失败；整个 attempt 再加墙钟上限，防住
# 「网关每 <300s 滴一行 keepalive 无限续期」的唯一真·无限挂起路径。
DEFAULT_LLM_FIRST_BYTE_TIMEOUT: float = 60.0   # env RA_LLM_FIRST_BYTE_TIMEOUT
DEFAULT_LLM_ATTEMPT_WALL_TIMEOUT: float = 1800.0  # env RA_LLM_ATTEMPT_WALL_TIMEOUT

# ---------------------------------------------------------------------------
# Tool output limits
# ---------------------------------------------------------------------------
OUTPUT_TRUNCATION_LIMIT: int = 30_000
OUTPUT_TRUNCATION_HALF: int = 15_000
#: 超限截断时插入的省略标记。此前这段 3 行拼接在 bash.py / python_exec.py /
#: frozen_exec.py 各复制一份（一字不差），改阈值或文案要改三处——正是那种
#: 漏改一处就静默分叉的典型。统一走 truncate_tool_output()。
OUTPUT_TRUNCATION_MARKER: str = "\n\n... (output truncated) ...\n\n"


def truncate_tool_output(result: str) -> str:
    """超长工具输出做**保头保尾**截断，中间替换为省略标记。

    三处执行工具（bash / run_python / frozen_exec）共用。放在 constants 是
    刻意的：它们只依赖这一个常量模块，不形成对 tools 包内部的相互依赖。
    """
    if len(result) <= OUTPUT_TRUNCATION_LIMIT:
        return result
    return (
        result[:OUTPUT_TRUNCATION_HALF]
        + OUTPUT_TRUNCATION_MARKER
        + result[-OUTPUT_TRUNCATION_HALF:]
    )

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


# ---------------------------------------------------------------------------
# Mid-execution steering（用户在回合进行中插入的实时纠正）
# ---------------------------------------------------------------------------
#: 引导消息前缀。agent.py 用它构造消息、cli.py 用它向模型解释协议——
#: 两处必须严格一致，提取常量防止漂移。
STEER_PREFIX: str = "[USER STEER]:"
