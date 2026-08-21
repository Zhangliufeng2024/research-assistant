"""Web interface for Research Assistant."""

from .app import create_app


def main():
    """Entry point: research-assistant-web command."""
    try:
        import uvicorn
    except ImportError as exc:
        print("Error: Web dependencies not installed.")
        print("Run: pip install research-assistant[web]")
        raise SystemExit(1) from exc

    uvicorn.run(
        "research_assistant.web.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
