"""Tool definitions and registry for the agent loop."""

from collections.abc import Awaitable, Callable
from typing import Any

from .bash import run_bash
from .citation_verify import verify_citations
from .file_ops import edit_file, glob_files, grep_search, read_file, write_file
from .python_exec import run_python

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
        "description": "Execute Python code and return stdout + stderr. The code is written to a temp file and run with the current Python interpreter. Useful for data analysis, figure generation, document creation, and computation.",
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
    "bash": run_bash,
    "glob_files": glob_files,
    "grep_search": grep_search,
    "run_python": run_python,
    "verify_citations": verify_citations,
}


class ToolRegistry:
    """Manages tool definitions and dispatches tool calls."""

    def __init__(self, work_dir: str = "."):
        self.work_dir = work_dir
        self._handlers = dict(_TOOL_HANDLERS)

    def get_schemas(self) -> list[dict[str, Any]]:
        return TOOL_DEFINITIONS

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool by name and return the result as a string."""
        handler = self._handlers.get(name)
        if handler is None:
            return f"Error: Unknown tool '{name}'. Available tools: {list(self._handlers.keys())}"

        # Inject sandbox restriction for file tools and citation verifier.
        # This prevents the LLM from reading or writing arbitrary paths outside
        # the configured work directory.
        if name in ("read_file", "write_file", "edit_file", "verify_citations"):
            if "sandbox" not in arguments:
                arguments["sandbox"] = self.work_dir

        if name in ("bash", "glob_files", "grep_search"):
            if "path" not in arguments or not arguments.get("path"):
                arguments["path"] = self.work_dir
            if name == "bash":
                arguments["cwd"] = arguments.pop("path", self.work_dir)

        if name == "run_python":
            if "cwd" not in arguments:
                arguments["cwd"] = self.work_dir

        try:
            result = await handler(**arguments)
            return result
        except Exception as e:
            return f"Error executing {name}: {e}"
