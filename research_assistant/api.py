"""Async API for programmatic scientific document generation."""

import os
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, AsyncGenerator

from .config import (
    load_project_env,
    resolve_model,
    build_system_instructions,
    generate_session_dir_name,
    build_llm_client,
)
from .agent import run_agent, AgentResult
from .tools.registry import ToolRegistry
from .retry import (
    ContextLimitError,
    get_max_retries,
    get_heartbeat_timeout,
)
from .core import (
    get_api_key,
    ensure_output_folder,
    get_data_files,
    process_data_files,
    setup_claude_skills,
)
from .models import ProgressUpdate, TextUpdate, PaperResult, PaperMetadata, PaperFiles, TokenUsage
from .utils import (
    scan_paper_directory,
    count_citations_in_bib,
    extract_citation_style,
    count_words_in_tex,
    extract_title_from_tex,
    count_words_in_docx,
    extract_title_from_docx,
)
from .orchestrator import run_orchestrated_generation


async def generate_paper(
    query: str,
    output_dir: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    data_files: Optional[List[str]] = None,
    cwd: Optional[str] = None,
    track_token_usage: bool = False,
    auto_continue: bool = True,
    multi_agent: bool = False,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Generate a scientific document asynchronously with progress updates."""
    start_time = time.time()

    work_dir = Path(cwd).resolve() if cwd else Path.cwd().resolve()
    load_project_env(work_dir)

    model = resolve_model(model)

    try:
        get_api_key(api_key)
    except ValueError as e:
        yield {"type": "progress", "stage": "error", "message": str(e)}
        yield {"type": "result", "status": "error", "message": str(e)}
        return

    package_dir = Path(__file__).parent.absolute()
    setup_claude_skills(package_dir, work_dir)
    output_folder = ensure_output_folder(work_dir, output_dir)

    yield ProgressUpdate(
        message=f"Initializing document generation with model: {model}",
        stage="initialization",
    ).to_dict()

    target_dir_name = generate_session_dir_name(query)
    system_instructions = build_system_instructions(work_dir, target_dir_name)

    if data_files:
        data_file_paths = get_data_files(work_dir, data_files)
        if data_file_paths:
            yield ProgressUpdate(
                message=f"Found {len(data_file_paths)} data file(s) to process",
                stage="initialization",
            ).to_dict()

    if auto_continue:
        env_auto_continue = os.environ.get("RA_AUTO_CONTINUE", "").lower()
        if env_auto_continue in ("false", "0", "no"):
            auto_continue = False

    # Multi-agent mode
    if multi_agent:
        output_folder = ensure_output_folder(work_dir, output_dir)
        paper_output_dir = work_dir / "writing_outputs" / target_dir_name

        yield ProgressUpdate(
            message=f"Multi-agent mode: orchestrating with model {model}",
            stage="initialization",
            details={"mode": "multi_agent", "model": model},
        ).to_dict()

        async for update in run_orchestrated_generation(
            query=query,
            model=model,
            work_dir=work_dir,
            output_dir=paper_output_dir,
            api_key=api_key,
            base_url=base_url,
            provider=provider,
        ):
            yield update

        file_info = scan_paper_directory(paper_output_dir)
        result = _build_paper_result(paper_output_dir, file_info)
        yield result.to_dict()
        return

    # Single-agent mode
    llm_client = build_llm_client(
        model=model, api_key=api_key, base_url=base_url, provider=provider,
    )
    tool_registry = ToolRegistry(work_dir=str(work_dir))

    collected_text_parts: list[str] = []
    tool_call_count = 0
    files_written: list[str] = []

    yield ProgressUpdate(
        message="Starting document generation",
        stage="initialization",
        details={
            "query_length": len(query),
            "max_retries": get_max_retries(),
            "heartbeat_timeout": get_heartbeat_timeout(),
        },
    ).to_dict()

    async def _on_text(text: str) -> None:
        collected_text_parts.append(text)
        # don't yield inside callback — just collect

    async def _on_tool(name: str, args: dict, result: str) -> None:
        nonlocal tool_call_count
        tool_call_count += 1
        if name == "write_file":
            fp = args.get("file_path", "")
            if fp:
                files_written.append(fp)

    try:
        agent_result = await run_agent(
            prompt=query,
            system_prompt=system_instructions,
            llm_client=llm_client,
            tools=tool_registry,
            auto_continue=auto_continue,
            on_text=_on_text,
            on_tool_use=_on_tool,
        )

        full_text = "".join(collected_text_parts)
        yield TextUpdate(content=full_text).to_dict()

        yield ProgressUpdate(
            message="Scanning output directory",
            stage="complete",
        ).to_dict()

        output_directory = _find_most_recent_output(output_folder, start_time)

        if not output_directory:
            error_result = _create_error_result("Output directory not found after generation")
            if track_token_usage:
                error_result['token_usage'] = agent_result.token_usage.to_dict()
            yield error_result
            return

        if data_files:
            data_file_paths = get_data_files(work_dir, data_files)
            if data_file_paths:
                processed_info = process_data_files(
                    work_dir, data_file_paths, str(output_directory), delete_originals=False,
                )
                if processed_info:
                    yield ProgressUpdate(
                        message=f"Processed {len(processed_info['all_files'])} file(s)",
                        stage="complete",
                    ).to_dict()

        file_info = scan_paper_directory(output_directory)
        result = _build_paper_result(output_directory, file_info)

        if track_token_usage:
            result.token_usage = agent_result.token_usage

        yield ProgressUpdate(message="Document generation complete", stage="complete").to_dict()
        yield result.to_dict()

    except ContextLimitError as e:
        error_result = _create_error_result(
            f"Context/token limit exceeded: {e.original}. Start a new session."
        )
        yield error_result
    except Exception as e:
        yield _create_error_result(f"Error during document generation: {e}")
    finally:
        await llm_client.close()


def _find_most_recent_output(output_folder: Path, start_time: float) -> Optional[Path]:
    """Find the most recently created/modified output directory."""
    try:
        output_dirs = [d for d in output_folder.iterdir() if d.is_dir()]
        if not output_dirs:
            return None
        recent_dirs = [d for d in output_dirs if d.stat().st_mtime >= start_time - 5]
        if not recent_dirs:
            recent_dirs = output_dirs
        return max(recent_dirs, key=lambda d: d.stat().st_mtime)
    except Exception:
        return None


def _build_paper_result(paper_dir: Path, file_info: Dict[str, Any]) -> PaperResult:
    """Build a comprehensive PaperResult from scanned files."""
    from datetime import datetime

    tex_file = file_info['tex_final'] or (file_info['tex_drafts'][0] if file_info['tex_drafts'] else None)
    docx_file = file_info.get('docx_final') or (file_info.get('docx_drafts', [])[0] if file_info.get('docx_drafts') else None)

    if docx_file:
        title = extract_title_from_docx(docx_file)
        word_count = count_words_in_docx(docx_file)
    else:
        title = extract_title_from_tex(tex_file)
        word_count = count_words_in_tex(tex_file)

    topic = ""
    parts = paper_dir.name.split('_', 2)
    if len(parts) >= 3:
        topic = parts[2].replace('_', ' ')

    metadata = PaperMetadata(
        title=title,
        created_at=datetime.fromtimestamp(paper_dir.stat().st_ctime).isoformat() + "Z",
        topic=topic,
        word_count=word_count,
    )

    files = PaperFiles(
        pdf_final=file_info['pdf_final'],
        tex_final=file_info['tex_final'],
        pdf_drafts=file_info['pdf_drafts'],
        tex_drafts=file_info['tex_drafts'],
        bibliography=file_info['bibliography'],
        figures=file_info['figures'],
        data=file_info['data'],
        progress_log=file_info['progress_log'],
        summary=file_info['summary'],
        docx_final=file_info.get('docx_final'),
        docx_drafts=file_info.get('docx_drafts', []),
    )

    citation_count = count_citations_in_bib(file_info['bibliography'])
    citation_style = extract_citation_style(file_info['bibliography'])

    citations = {
        'count': citation_count,
        'style': citation_style,
        'file': file_info['bibliography'],
    }

    status = "success"
    has_final = file_info['pdf_final'] is not None or file_info.get('docx_final') is not None
    compilation_success = has_final
    if not has_final:
        has_draft = (file_info['tex_final'] is not None
                     or bool(file_info.get('docx_drafts'))
                     or bool(file_info.get('tex_drafts')))
        status = "partial" if has_draft else "failed"

    return PaperResult(
        status=status,
        paper_directory=str(paper_dir),
        paper_name=paper_dir.name,
        metadata=metadata,
        files=files,
        citations=citations,
        figures_count=len(file_info['figures']),
        compilation_success=compilation_success,
        errors=[],
    )


def _create_error_result(error_message: str) -> Dict[str, Any]:
    return PaperResult(
        status="failed",
        paper_directory="",
        paper_name="",
        errors=[error_message],
    ).to_dict()
