"""Tool definitions and registry for the agent loop."""

from collections.abc import Awaitable, Callable
from typing import Any

from .citation_verify import verify_citations
from .exec_provider import ExecProvider, LocalExecProvider
from .file_ops import edit_file, glob_files, grep_search, read_file, write_file

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
]


def get_tool_schemas() -> list[dict[str, Any]]:
    """Return tool definitions in the unified format (works for both providers)."""
    return TOOL_DEFINITIONS


_TOOL_HANDLERS: dict[str, Callable[..., Awaitable[str]]] = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "glob_files": glob_files,
    "grep_search": grep_search,
    "verify_citations": verify_citations,
}


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
    ):
        self.work_dir = work_dir
        self.write_anchor = write_anchor
        self.exec_cwd = exec_cwd or work_dir
        self._handlers = dict(_TOOL_HANDLERS)
        # Execution-world seam: defaults to the local provider. Swapping in a
        # container/remote provider moves bash/run_python wholesale.
        self.exec_provider: ExecProvider = exec_provider if exec_provider is not None else LocalExecProvider()

    def get_schemas(self) -> list[dict[str, Any]]:
        return TOOL_DEFINITIONS

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool by name and return the result as a string."""
        # Execution-provider tools are dispatched through the seam *before* the
        # handler lookup: bash/run_python no longer live in _TOOL_HANDLERS, so
        # swapping self.exec_provider moves the whole execution world (container,
        # remote sandbox) without touching tool definitions. Argument
        # normalization below is identical to what the local handlers received
        # before the seam was introduced (no duplication, no loss).
        if name == "bash":
            if "path" not in arguments or not arguments.get("path"):
                arguments["path"] = self.exec_cwd
            arguments["cwd"] = arguments.pop("path", self.exec_cwd)
            try:
                return await self.exec_provider.run_bash(
                    command=arguments.get("command", ""),
                    timeout=int(arguments.get("timeout", 120)),
                    cwd=arguments.get("cwd", self.exec_cwd),
                )
            except Exception as e:
                return f"Error executing {name}: {e}"

        if name == "run_python":
            if "cwd" not in arguments:
                arguments["cwd"] = self.exec_cwd
            try:
                # workspace_root 恒取 work_dir（工作区根），与 cwd 解耦：
                # 会话模式下 cwd 可能是产物目录，而 WS 必须指向根
                return await self.exec_provider.run_python(
                    code=arguments.get("code", ""),
                    timeout=int(arguments.get("timeout", 120)),
                    cwd=arguments.get("cwd", self.exec_cwd),
                    workspace_root=self.work_dir,
                )
            except Exception as e:
                return f"Error executing {name}: {e}"

        handler = self._handlers.get(name)
        if handler is None:
            return f"Error: Unknown tool '{name}'. Available tools: {list(self._handlers.keys())}"

        # Inject sandbox restriction for file tools and citation verifier.
        # This prevents the LLM from reading or writing arbitrary paths outside
        # the configured work directory.
        if name in ("read_file", "write_file", "edit_file", "verify_citations"):
            if "sandbox" not in arguments:
                arguments["sandbox"] = self.work_dir
        if name == "write_file" and self.write_anchor is not None:
            arguments.setdefault("write_anchor", self.write_anchor)

        if name in ("glob_files", "grep_search"):
            if "path" not in arguments or not arguments.get("path"):
                arguments["path"] = self.work_dir

        try:
            result = await handler(**arguments)
            return result
        except Exception as e:
            return f"Error executing {name}: {e}"
