"""Data models for research assistant API responses."""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, timezone


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
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    message: str = ""
    stage: Literal["initialization", "planning", "research", "writing", "compilation", "complete"] = "initialization"
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
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
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class PaperMetadata:
    """Metadata about the generated paper."""
    title: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    topic: str = ""
    word_count: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class PaperFiles:
    """File paths for all generated paper artifacts."""
    pdf_final: Optional[str] = None
    tex_final: Optional[str] = None
    pdf_drafts: List[str] = field(default_factory=list)
    tex_drafts: List[str] = field(default_factory=list)
    bibliography: Optional[str] = None
    figures: List[str] = field(default_factory=list)
    data: List[str] = field(default_factory=list)
    progress_log: Optional[str] = None
    summary: Optional[str] = None
    docx_final: Optional[str] = None
    docx_drafts: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
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
    model: Optional[str] = None  # Which model was used (needed for cost analysis)
    
    @property
    def total_tokens(self) -> int:
        """Calculate total tokens (input + output)."""
        return self.input_tokens + self.output_tokens
    
    def to_dict(self) -> Dict[str, Any]:
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
    citations: Dict[str, Any] = field(default_factory=dict)
    figures_count: int = 0
    compilation_success: bool = False
    errors: List[str] = field(default_factory=list)
    token_usage: Optional[TokenUsage] = None
    
    def to_dict(self) -> Dict[str, Any]:
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

