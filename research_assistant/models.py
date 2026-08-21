"""Data models for research assistant API responses."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


def _utc_iso_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class ProgressUpdate:
    """Progress update during document generation.
    
    Attributes:
        type: Always "progress" to distinguish from result messages
        timestamp: ISO 8601 timestamp of the update
        message: Human-readable progress message
        stage: Current workflow stage (initialization|planning|research|writing|compilation|complete)
        details: Optional dictionary with additional context (tool name, files created, etc.)
    """
    type: str = "progress"
    timestamp: str = field(default_factory=lambda: _utc_iso_now())
    message: str = ""
    stage: Literal["initialization", "planning", "research", "writing", "compilation", "complete"] = "initialization"
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        # Keep details as null rather than silently removing the field,
        # so callers can rely on the key always being present.
        return result


@dataclass
class TextUpdate:
    """Live text output from Research Assistant during document generation.

    Streams Research Assistant's actual text responses in real-time, allowing API consumers
    to display the AI's reasoning and explanations as they happen.

    Attributes:
        type: Always "text" to distinguish from progress and result messages
        content: The text content from Research Assistant's response
    """
    type: str = "text"
    content: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class PaperMetadata:
    """Metadata about the generated paper."""
    title: str | None = None
    created_at: str = field(default_factory=lambda: _utc_iso_now())
    topic: str = ""
    word_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class PaperFiles:
    """File paths for all generated paper artifacts."""
    pdf_final: str | None = None
    tex_final: str | None = None
    pdf_drafts: list[str] = field(default_factory=list)
    tex_drafts: list[str] = field(default_factory=list)
    bibliography: str | None = None
    figures: list[str] = field(default_factory=list)
    data: list[str] = field(default_factory=list)
    progress_log: str | None = None
    summary: str | None = None
    docx_final: str | None = None
    docx_drafts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class TokenUsage:
    """Token usage statistics.
    
    Attributes:
        input_tokens: Total input tokens consumed
        output_tokens: Total output tokens consumed
        cache_creation_input_tokens: Tokens used for cache creation
        cache_read_input_tokens: Tokens read from cache
    """
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    model: str | None = None  # Which model was used (needed for cost analysis)

    @property
    def total_tokens(self) -> int:
        """Calculate total tokens (input + output)."""
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        result['total_tokens'] = self.total_tokens
        return result


@dataclass
class PaperResult:
    """Final result containing all information about the generated paper."""
    type: str = "result"
    status: Literal["success", "partial", "failed"] = "success"
    paper_directory: str = ""
    paper_name: str = ""
    metadata: PaperMetadata = field(default_factory=PaperMetadata)
    files: PaperFiles = field(default_factory=PaperFiles)
    citations: dict[str, Any] = field(default_factory=dict)
    figures_count: int = 0
    compilation_success: bool = False
    errors: list[str] = field(default_factory=list)
    token_usage: TokenUsage | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        # Ensure nested objects are also dictionaries
        if isinstance(self.metadata, PaperMetadata):
            result['metadata'] = self.metadata.to_dict()
        if isinstance(self.files, PaperFiles):
            result['files'] = self.files.to_dict()
        if isinstance(self.token_usage, TokenUsage):
            result['token_usage'] = self.token_usage.to_dict()
        elif self.token_usage is None:
            del result['token_usage']
        return result

