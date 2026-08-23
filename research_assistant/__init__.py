"""
Research Assistant - AI-powered research and writing assistant.

Example:
    import asyncio
    from research_assistant import generate_paper

    async def main():
        async for update in generate_paper("Create a paper on transformer attention mechanisms"):
            if update["type"] == "text":
                print(update["content"], end="", flush=True)
            elif update["type"] == "result":
                print(f"\\nPaper created: {update['paper_directory']}")

    asyncio.run(main())

    CLI usage::

        $ research-assistant
        > Create a NeurIPS paper on transformer attention mechanisms
"""

from .api import generate_paper
from .config import build_llm_client, resolve_model
from .models import PaperFiles, PaperMetadata, PaperResult, ProgressUpdate, TextUpdate, TokenUsage
from .orchestrator import run_orchestrated_generation

__version__ = "3.3.3"
__author__ = "zhangliufeng"
__license__ = "MIT"

__all__ = [
    "generate_paper",
    "run_orchestrated_generation",
    "ProgressUpdate",
    "TextUpdate",
    "PaperResult",
    "PaperMetadata",
    "PaperFiles",
    "TokenUsage",
]
