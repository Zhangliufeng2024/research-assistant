"""Tool definitions and registry for the agent loop."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..artifacts import ArtifactVersionStore
from ..core import safe_resolve
from .citation_verify import verify_citations
from .exec_provider import ExecProvider, LocalExecProvider
from .file_ops import apply_patch, edit_file, glob_files, grep_search, read_file, write_file
from .research_os import (
    list_research_ledger,
    record_research_claim,
    record_research_decision,
    record_research_evidence,
    record_research_item,
)

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "Read the contents of a file. Returns the file content with line numbers.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to the file to read."},
                "offset": {"type": "integer", "description": "Line number to start reading from (0-based). Default 0.", "default": 0},
                "limit": {"type": "integer", "description": "Maximum number of lines to read. Default 2000.", "default": 2000},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file, creating it if it doesn't exist or overwriting if it does.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to the file to write."},
                "content": {"type": "string", "description": "The content to write to the file."},
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Perform an exact string replacement in a file. The old_string must appear exactly once in the file.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to the file to edit."},
                "old_string": {"type": "string", "description": "The exact text to find and replace."},
                "new_string": {"type": "string", "description": "The text to replace it with."},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
    {
        "name": "bash",
        "description": "Execute a bash command and return its output (stdout + stderr).",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to execute."},
                "timeout": {"type": "integer", "description": "Timeout in seconds. Default 120.", "default": 120},
            },
            "required": ["command"],
        },
    },
    {
        "name": "glob_files",
        "description": "Find files matching a glob pattern. Returns a list of matching file paths.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern to match (e.g. '**/*.py', 'src/**/*.tex')."},
                "path": {"type": "string", "description": "Directory to search in. Defaults to working directory."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep_search",
        "description": "Search for a regex pattern in files. Returns matching lines with file paths and line numbers.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for."},
                "path": {"type": "string", "description": "File or directory to search in. Defaults to working directory."},
                "glob": {"type": "string", "description": "Glob filter for filenames (e.g. '*.py')."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "run_python",
        "description": (
            "Execute Python code in-process and return stdout + stderr. This is the ONLY "
            "way to run Python: never invoke python/pip via bash or subprocess (in packaged "
            "builds there is no system Python — sys.executable is the app itself). numpy, "
            "pandas and matplotlib are available; to run a .py script file use the injected "
            "helper run_script(path, argv=None) inside run_python (frozen builds also expose "
            "the workspace root as the global WS). Useful for data analysis, figure "
            "generation, document creation, and computation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute."},
                "timeout": {"type": "integer", "description": "Timeout in seconds. Default 120.", "default": 120},
            },
            "required": ["code"],
        },
    },
    {
        "name": "apply_patch",
        "description": (
            "Apply a batch of exact-replacement edits across one or more files "
            "atomically. Each element of 'patches' is {file_path, old_string, "
            "new_string}; old_string must appear exactly once in its file. "
            "If ANY patch fails, no file is modified (all-or-nothing). Use this "
            "instead of repeated edit_file calls when several targeted changes "
            "must land together."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "patches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Path to the file to edit."},
                            "old_string": {"type": "string", "description": "Exact text to find (must be unique)."},
                            "new_string": {"type": "string", "description": "Replacement text."},
                        },
                        "required": ["file_path", "old_string", "new_string"],
                    },
                    "description": "Non-empty list of edits to apply.",
                },
            },
            "required": ["patches"],
        },
    },
    {
        "name": "verify_citations",
        "description": (
            "Verify all BibTeX citations in a .bib file against Crossref, Semantic Scholar, "
            "and OpenAlex. Returns a verification report with per-citation confidence scores. "
            "MANDATORY: call this after assembling references.bib. "
            "Any UNVERIFIED citations must be replaced before paper submission."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "bib_file": {
                    "type": "string",
                    "description": "Absolute path to the .bib file to verify.",
                },
                "output_file": {
                    "type": "string",
                    "description": (
                        "Optional absolute path to save the Markdown report "
                        "(e.g. sources/CITATION_VERIFICATION.md)."
                    ),
                },
            },
            "required": ["bib_file"],
        },
    },
    {
        "name": "record_research_claim",
        "description": (
            "把一条可核查的科学论断写入项目研究台账。返回新记录的 claim_id，"
            "后续挂证据时引用。记录会出现在 Project Home 证据矩阵并参与综合写作门禁。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "statement": {
                    "type": "string",
                    "description": "主张正文：一句可被证据支持或反驳的完整论断。",
                },
                "status": {
                    "type": "string",
                    "description": "主张状态，默认 proposed（ proposed / confirmed / rejected 等）。",
                    "default": "proposed",
                },
                "confidence": {
                    "type": "number",
                    "description": "置信度，0 到 1 之间的小数，可省略。",
                },
            },
            "required": ["statement"],
        },
    },
    {
        "name": "record_research_evidence",
        "description": (
            "为已有主张挂一条支撑证据并自动建立 supports 链接。每条主张至少需要"
            "一条证据才能满足 Project Home 的综合写作门禁。返回 evidence_id。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "claim_id": {
                    "type": "string",
                    "description": "目标主张 id（来自 record_research_claim 的返回或 list_research_ledger 查询）。",
                },
                "source_title": {
                    "type": "string",
                    "description": "证据出处名称，如论文标题、报告名。",
                },
                "source_url": {
                    "type": "string",
                    "description": "证据来源 URL 或 DOI，可省略。",
                    "default": "",
                },
                "note": {
                    "type": "string",
                    "description": "证据摘录或说明文字，可省略。",
                    "default": "",
                },
            },
            "required": ["claim_id", "source_title"],
        },
    },
    {
        "name": "record_research_item",
        "description": (
            "登记一个研究对象条目：研究问题(question)、假设(hypothesis)、"
            "目标(objective)或备注(note)。返回 item_id。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "条目标题。"},
                "kind": {
                    "type": "string",
                    "description": "类型：question / hypothesis / objective / note，默认 question。",
                    "default": "question",
                },
                "notes": {
                    "type": "string",
                    "description": "补充说明正文，可省略。",
                    "default": "",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "record_research_decision",
        "description": (
            "把一个关键研究取舍（方法选型、口径确定、范围裁剪等）落账为决策记录，"
            "便于审计追溯。返回 decision_id。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "决策标题：概括做了什么决定。"},
                "rationale": {
                    "type": "string",
                    "description": "决策理由与依据，可省略。",
                    "default": "",
                },
                "status": {
                    "type": "string",
                    "description": "决策状态，默认 active。",
                    "default": "active",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_research_ledger",
        "description": (
            "列出研究台账现有研究对象/主张/证据/决策概览。引用任何台账记录 id "
            "之前应先用它自查有效 id，不要凭记忆猜测。"
        ),
        "parameters": {"type": "object", "properties": {}},
    },
]


def get_tool_schemas() -> list[dict[str, Any]]:
    """Return tool definitions in the unified format (works for both providers).

    返回拷贝而非全局表本身：调用方拿到后通常会 append 自定义工具，直接给
    TOOL_DEFINITIONS 会让改动永久留在模块级状态里（同 ``get_schemas`` 的
    教训）。当前项目内无调用点，但这是公开 API，防御性地返回副本。
    """
    return list(TOOL_DEFINITIONS)


_TOOL_HANDLERS: dict[str, Callable[..., Awaitable[str]]] = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "apply_patch": apply_patch,
    "glob_files": glob_files,
    "grep_search": grep_search,
    "verify_citations": verify_citations,
    "record_research_claim": record_research_claim,
    "record_research_evidence": record_research_evidence,
    "record_research_item": record_research_item,
    "record_research_decision": record_research_decision,
    "list_research_ledger": list_research_ledger,
}


@dataclass(frozen=True)
class ToolExtension:
    """A process-local, declaratively registered extra tool.

    Extensions let hosts (CLI, web, tests) attach new capabilities to the agent
    loop without modifying the built-in hander table. They are resolved at
    ``ToolRegistry.register_extension`` time and merged into the schema list
    returned by :meth:`ToolRegistry.get_schemas`, so the LLM sees them as any
    other tool. The handler may be sync or async and receives the raw
    (model-supplied) arguments dict as keyword arguments.
    """

    name: str
    description: str
    schema: dict[str, Any] = field(default_factory=dict)
    handler: Callable[..., Awaitable[str] | str] | None = None

    def to_definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.schema or {"type": "object", "properties": {}},
        }

# 研究台账工具：workspace 不面向模型暴露，由 registry 注入（见 execute）。
# sandbox 围栏 work_dir 即工作区根，<root>/.ra/platform.sqlite3 恒在其下，
# 因此无需给 ToolRegistry 增加任何构造参数。
_RESEARCH_LEDGER_TOOLS = frozenset({
    "record_research_claim",
    "record_research_evidence",
    "record_research_item",
    "record_research_decision",
    "list_research_ledger",
})

_EXEC_SNAPSHOT_EXCLUDES = frozenset({".ra", ".git", "__pycache__", "node_modules"})
_EXEC_SNAPSHOT_MAX_FILES = 512
_EXEC_SNAPSHOT_MAX_BYTES = 32 * 1024 * 1024

# 修复 F：执行超时钳位——0/负数会立即超时或永挂，无界值会长期占用执行槽。
_EXEC_TIMEOUT_MIN_S = 5
_EXEC_TIMEOUT_MAX_S = 600


def _clamp_timeout(raw: Any) -> int:
    """把模型传入的执行超时钳位到 [5, 600] 秒；垃圾值回默认 120。"""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 120
    return max(_EXEC_TIMEOUT_MIN_S, min(_EXEC_TIMEOUT_MAX_S, value))


@dataclass(frozen=True)
class SnapshotStats:
    """一次执行快照的覆盖情况（A+ 阶段 2 / F-4）。

    此前超限丢弃是**完全静默**的：文件数到 512 直接 return、字节超限直接
    continue，回执只报「已记录 N 个变更」，用户无从得知有多少产物其实没进
    版本历史。于是「变更」页看起来什么都有，真要恢复时才发现缺了一大半。
    """

    files_captured: int = 0
    #: 文件数达到上限后中止扫描（剩余文件全部未被扫描，无法精确计数）
    truncated: bool = False
    #: 因单文件过大或累计超字节上限而被跳过的文件数
    oversized_skipped: int = 0
    #: 按名排除的执行中间脚本（_ra_exec_*.py）——有意排除，不算「漏网」
    exec_scripts_skipped: int = 0

    @property
    def has_gaps(self) -> bool:
        return self.truncated or self.oversized_skipped > 0

    def notice(self) -> str:
        """给模型的中文提示；无缺口时返回空串。"""
        if not self.has_gaps:
            return ""
        parts: list[str] = []
        if self.truncated:
            parts.append(f"文件数达到上限 {_EXEC_SNAPSHOT_MAX_FILES}，部分产物未被扫描")
        if self.oversized_skipped:
            cap_mb = _EXEC_SNAPSHOT_MAX_BYTES // (1024 * 1024)
            parts.append(f"{self.oversized_skipped} 个文件因超过 {cap_mb}MB 上限被跳过")
        return f"（注意：{'；'.join(parts)}，这些文件未纳入版本跟踪，无法恢复）"


def _snapshot_exec_outputs(
    roots: list[Path], workspace: Path,
) -> tuple[dict[Path, bytes], SnapshotStats]:
    """Bounded recursive snapshot around an execution tool invocation.

    Script tools can create many files without going through ``write_file``.
    Capture their before/after bytes in the same version store while keeping
    scanning bounded so an analysis job cannot stall the event loop.

    Returns:
        ``(snapshot, stats)``。stats 描述**未被覆盖**的部分，调用方必须把它
        呈现出来（A+ 阶段 2 / F-4）——静默丢弃会让用户误以为产物全都被版本化了。
    """
    snapshot: dict[Path, bytes] = {}
    total = 0
    seen: set[Path] = set()
    oversized_skipped = 0
    exec_scripts_skipped = 0
    truncated = False
    for root in roots:
        try:
            root = safe_resolve(root, workspace)
        except ValueError:
            continue
        if not root.exists() or root in seen:
            continue
        seen.add(root)
        candidates = [root] if root.is_file() else root.rglob("*")
        for path in candidates:
            if len(snapshot) >= _EXEC_SNAPSHOT_MAX_FILES:
                truncated = True
                break
            if any(part in _EXEC_SNAPSHOT_EXCLUDES for part in path.parts):
                continue
            try:
                resolved = safe_resolve(path, workspace)
                if not resolved.is_file():
                    continue
                if resolved.name.startswith("_ra_exec_"):
                    exec_scripts_skipped += 1
                    continue
                size = resolved.stat().st_size
                if size > _EXEC_SNAPSHOT_MAX_BYTES or total + size > _EXEC_SNAPSHOT_MAX_BYTES:
                    oversized_skipped += 1
                    continue
                snapshot[resolved] = resolved.read_bytes()
                total += size
            except (OSError, ValueError):
                continue
        if truncated:
            break
    return snapshot, SnapshotStats(
        files_captured=len(snapshot),
        truncated=truncated,
        oversized_skipped=oversized_skipped,
        exec_scripts_skipped=exec_scripts_skipped,
    )


class ToolRegistry:
    """Manages tool definitions and dispatches tool calls.

    R12 P2 双轨制注入点：
    - ``write_anchor``：write_file 相对路径的确定性落点（会话=outputs/<sid>，
      任务=论文目录）；不设则维持旧行为（相对路径落工作区根）。
    - ``exec_cwd``：bash/run_python 的默认 CWD（会话=产物目录，savefig 相对
      保存自动归家）；不设则与 work_dir 相同（任务模式语义不变）。
    sandbox 恒为 work_dir——读写围栏不随归巢改变。
    """

    def __init__(
        self,
        work_dir: str = ".",
        exec_provider: ExecProvider | None = None,
        write_anchor: str | None = None,
        exec_cwd: str | None = None,
        allowed_tools: tuple[str, ...] | list[str] | None = None,
        artifact_store: Any | None = None,
        artifact_session: str | None = None,
    ):
        self.work_dir = work_dir
        self.write_anchor = write_anchor
        self.exec_cwd = exec_cwd or work_dir
        self.allowed_tools = frozenset(str(item) for item in allowed_tools) if allowed_tools else None
        self._handlers = dict(_TOOL_HANDLERS)
        #: Declarative extra tools attached by hosts (see :class:`ToolExtension`).
        self.extensions: dict[str, ToolExtension] = {}
        self.version_store = ArtifactVersionStore(work_dir)
        # Execution-world seam: defaults to the local provider. Swapping in a
        # container/remote provider moves bash/run_python wholesale.
        self.exec_provider: ExecProvider = exec_provider if exec_provider is not None else LocalExecProvider()
        # A+ 阶段 2 / F-2：产物索引**推模式**回填。
        #
        # 此前 artifacts 表只在有人调用 `/chat/sessions/{id}/manifest` 时才被
        # 拉模式回填（chat.py 的 replace_artifacts），也就是说：**没人查就不
        # 记**。结果是同一份"产生了哪些文件"在 6 处各记一份且互不一致。
        # 会话宿主把 PlatformStore 与 session_id 注入进来，工具写成功即回填，
        # 让这张表成为唯一权威；manifest.json / artifact_reviews 降为派生视图。
        # CLI / 单代理路径不注入（None）→ 行为与现状完全一致。
        self.artifact_store = artifact_store
        self.artifact_session = artifact_session or ""

    def _notify_artifact(self, path: Path) -> None:
        """写入成功后把产物推入索引（F-2 推模式）。

        索引失败**绝不能**影响写入本身——它是辅助视图，不是数据。失败仅记
        debug，留待下一次 manifest 重建兜底。
        """
        if self.artifact_store is None or not self.artifact_session:
            return
        try:
            self.artifact_store.upsert_artifact(
                self.artifact_session, path, workspace=Path(self.work_dir),
            )
        except Exception:  # noqa: BLE001 — 索引是旁路，不阻断主路径
            logging.getLogger(__name__).debug(
                "产物索引回填失败 path=%s", path, exc_info=True,
            )

    def get_schemas(self) -> list[dict[str, Any]]:
        # 必须是拷贝：下方要向 base 追加扩展定义，而 allowed_tools is None 时
        # 直接拿 TOOL_DEFINITIONS 会让 append 写进模块级列表——那会永久污染
        # 全局工具表（连新建的、从未注册扩展的 registry 也会看到别人家的
        # 扩展），且每次调用都膨胀，重复 schema 每回合重复发给模型。
        base: list[dict[str, Any]]
        if self.allowed_tools is None:
            base = list(TOOL_DEFINITIONS)
        else:
            base = [schema for schema in TOOL_DEFINITIONS if schema.get("name") in self.allowed_tools]
        # Merge declarative extensions into the visible tool surface.
        for ext in self.extensions.values():
            if self.allowed_tools is not None and ext.name not in self.allowed_tools:
                continue
            base.append(ext.to_definition())
        return base

    def register_extension(self, ext: ToolExtension) -> None:
        """Attach a declarative extra tool so the loop can call it.

        The name must not collide with a built-in tool. The handler may be sync
        or async; it receives the model-supplied arguments as keyword args.
        """
        if not ext.name:
            raise ValueError("extension must have a non-empty name")
        if ext.name in _TOOL_HANDLERS or ext.name == "bash" or ext.name == "run_python":
            raise ValueError(f"extension name {ext.name!r} collides with a built-in tool")
        if ext.handler is None:
            raise ValueError(f"extension {ext.name!r} has no handler")
        self.extensions[ext.name] = ext

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool by name and return the result as a string.

        A+ 阶段 3 / A-2 拆分后的分发骨架：本方法只做**顺序**决策——
        extensions → 执行缝（bash/run_python）→ apply_patch → 通用 handler。
        每个分支的细节在自己的私有方法里；所有分支的错误都以 ``Error …``
        字符串返回（模型可读），不向上抛。
        """
        if self.allowed_tools is not None and name not in self.allowed_tools:
            return f"Error: 工具 {name} 不在当前 Agent 的允许列表中"
        if name in self.extensions:
            return await self._execute_extension(name, arguments)
        if name in ("bash", "run_python"):
            return await self._execute_via_provider(name, arguments)
        if name == "apply_patch":
            return await self._execute_apply_patch(arguments)
        return await self._execute_handler(name, arguments)

    async def _execute_extension(self, name: str, arguments: dict[str, Any]) -> str:
        """声明式扩展优先派发（它们不在 _TOOL_HANDLERS 里）。"""
        ext = self.extensions[name]
        try:
            result = ext.handler(**arguments)
            if asyncio.iscoroutine(result):
                result = await result
            return str(result)
        except Exception as e:  # noqa: BLE001 — untrusted handler; report and continue
            return f"Error executing extension {name}: {e}"

    async def _execute_via_provider(self, name: str, arguments: dict[str, Any]) -> str:
        """bash / run_python：经执行缝派发（交换 exec_provider 即整体迁移执行世界）。

        两工具共享同一骨架：cwd 围栏解析 → 前置快照 → 调用 provider →
        版本回填。差异只在参数归一（bash 有 path→cwd 的历史双键口径）与
        provider 调用形状（run_python 额外带 workspace_root：会话模式下
        cwd 可能是产物目录，而 WS 必须恒指工作区根）。
        """
        if name == "bash":
            if not arguments.get("path"):
                arguments["path"] = self.exec_cwd
            arguments["cwd"] = arguments.pop("path", self.exec_cwd)
        else:
            arguments.setdefault("cwd", self.exec_cwd)

        async def run(cwd: str) -> str:
            timeout = _clamp_timeout(arguments.get("timeout", 120))
            if name == "bash":
                return await self.exec_provider.run_bash(
                    command=arguments.get("command", ""), timeout=timeout, cwd=cwd,
                )
            return await self.exec_provider.run_python(
                code=arguments.get("code", ""), timeout=timeout, cwd=cwd,
                workspace_root=self.work_dir,
            )

        try:
            raw_cwd = Path(str(arguments.get("cwd") or self.exec_cwd))
            workspace = Path(self.work_dir)
            cwd = safe_resolve(
                raw_cwd if raw_cwd.is_absolute() else workspace / raw_cwd, workspace,
            )
            snapshot_roots = [Path(self.write_anchor)] if self.write_anchor else [cwd]
            before, _before_stats = await asyncio.to_thread(
                _snapshot_exec_outputs, snapshot_roots, Path(self.work_dir),
            )
            result = await run(str(cwd))
            return await self._record_exec_changes(before, snapshot_roots, name, result)
        except ValueError:
            return f"Error executing {name}: working directory escapes workspace"
        except Exception as e:
            return f"Error executing {name}: {e}"

    async def _execute_apply_patch(self, arguments: dict[str, Any]) -> str:
        """多文件批量编辑：注入 sandbox/anchor（模型从不传），与执行工具共用
        快照式版本记录，批量编辑同样可在「变更」页 diff/恢复。

        快照根与执行工具不同：fallback 恒取工作区根而非 cwd——批量补丁
        可能落在 anchor 之外的任意工作区路径。
        """
        arguments["sandbox"] = self.work_dir
        if self.write_anchor is not None:
            arguments["write_anchor"] = self.write_anchor
        snapshot_roots = [Path(self.write_anchor)] if self.write_anchor else [Path(self.work_dir)]
        before, _before_stats = await asyncio.to_thread(
            _snapshot_exec_outputs, snapshot_roots, Path(self.work_dir),
        )
        try:
            result = await apply_patch(
                patches=arguments.get("patches"),
                sandbox=arguments.get("sandbox", self.work_dir),
                write_anchor=arguments.get("write_anchor"),
            )
        except Exception as e:
            return f"Error executing apply_patch: {e}"
        return await self._record_exec_changes(before, snapshot_roots, "apply_patch", result)

    async def _execute_handler(self, name: str, arguments: dict[str, Any]) -> str:
        """通用 handler 路径：围栏注入 → 路径预解析 → 调用 → 版本记录 + 推送。"""
        handler = self._handlers.get(name)
        if handler is None:
            return f"Error: Unknown tool '{name}'. Available tools: {list(self._handlers.keys())}"

        # Inject sandbox restriction for file tools and citation verifier.
        # This prevents the LLM from reading or writing arbitrary paths outside
        # the configured work directory.
        # 安全修复 C：**无条件覆盖**——补缺式注入（if key not in arguments）会被
        # 模型自带的伪造 sandbox 键绕过围栏；write_anchor 同理先 pop 再注入。
        if name in (
            "read_file", "write_file", "edit_file", "glob_files", "grep_search",
            "verify_citations",
        ):
            arguments["sandbox"] = self.work_dir
        # 研究台账工具同理无条件覆盖注入 workspace（模型传入的一律丢弃）：
        # 库路径由工作区根推导，模型不需要也不应该自己传路径。
        if name in _RESEARCH_LEDGER_TOOLS:
            arguments["workspace"] = self.work_dir
        # write_anchor 只能由 registry 配置决定：模型传入的一律丢弃
        if name == "write_file":
            arguments.pop("write_anchor", None)
        # 修复 G：read/edit/write 同一 anchor 口径，双轨一致
        if self.write_anchor is not None and name in (
            "read_file", "edit_file", "write_file",
        ):
            arguments["write_anchor"] = self.write_anchor

        if name in ("glob_files", "grep_search"):
            if "path" not in arguments or not arguments.get("path"):
                arguments["path"] = self.work_dir

        tracked_path = None
        before_bytes = None
        if name in ("write_file", "edit_file"):
            raw = Path(str(arguments.get("file_path") or ""))
            if raw:
                root = Path(self.work_dir)
                anchor = Path(self.write_anchor) if self.write_anchor else None
                try:
                    if raw.is_absolute():
                        tracked_path = safe_resolve(raw, root)
                    elif name == "write_file":
                        base = anchor if anchor is not None else root
                        tracked_path = safe_resolve(base / raw, root)
                    else:
                        # 修复 G：与 file_ops.edit_file 同口径——anchor 优先存在性，
                        # 否则根，保证版本跟踪记录的是真正被编辑的那个副本。
                        tracked_path = safe_resolve(root / raw, root)
                        if anchor is not None:
                            candidate = safe_resolve(anchor / raw, root)
                            if candidate.exists():
                                tracked_path = candidate
                    before_bytes = tracked_path.read_bytes() if tracked_path.is_file() else None
                except (ValueError, OSError):
                    tracked_path = None
        try:
            result = await handler(**arguments)
            if (
                tracked_path is not None
                and not result.startswith("Error")
            ):
                after_bytes = tracked_path.read_bytes() if tracked_path.is_file() else None
                try:
                    self.version_store.record(
                        tracked_path, before_bytes, after_bytes, tool=name,
                    )
                except (OSError, ValueError):
                    pass  # 尽力而为：版本登记是旁路可观测性，失败不影响工具写入本身
                # A+ 阶段 2 / F-2：写入成功即推入产物索引。此前的拉模式只在
                # 有人调 manifest 端点时才回填——没人查就不记。旁路失败
                # 不影响写入本身。
                self._notify_artifact(tracked_path)
            return result
        except Exception as e:
            return f"Error executing {name}: {e}"

    async def _record_exec_changes(
        self,
        before: dict[Path, bytes],
        roots: list[Path],
        tool: str,
        result: str,
    ) -> str:
        """Append indirect script writes/deletions to recoverable history.

        A+ 阶段 2 / F-4：扫描本身也可能**漏掉**一部分文件（数量/字节上限），
        这种情况必须在回执里说清楚。否则用户会以为产物都已纳入版本跟踪，
        直到某天想恢复时才发现快照根本不存在——而那时（修复前）恢复动作
        还会把当前文件删掉。
        """
        workspace = Path(self.work_dir)
        after, after_stats = await asyncio.to_thread(
            _snapshot_exec_outputs, roots, workspace,
        )
        changed = 0
        for path in sorted(set(before) | set(after)):
            try:
                if self.version_store.record(path, before.get(path), after.get(path), tool=tool):
                    changed += 1
                    # F-2 推模式：间接写入同样要进产物索引。只对实际发生
                    # 变化的路径通知（before==after 的路径没有新版本）。
                    self._notify_artifact(path)
            except (OSError, ValueError):
                continue
        if changed == 0:
            # 一个变更都没记录时，若扫描有缺口更要说清楚——否则用户只会
            # 读到「没有变更」这个错误结论。
            return f"{result}{after_stats.notice()}".rstrip() if after_stats.has_gaps else result
        return (
            f"{result}\n\n[已记录 {changed} 个脚本产物变更，可在“变更”页审阅或恢复]"
            f"{after_stats.notice()}"
        )
