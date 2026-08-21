"""REST API routes for papers listing, detail, and file serving."""

import mimetypes
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ..core import safe_resolve
from ..utils import (
    count_citations_in_bib,
    count_words_in_docx,
    count_words_in_tex,
    extract_title_from_docx,
    extract_title_from_tex,
    find_existing_papers,
    scan_paper_directory,
)

router = APIRouter()


def _paper_summary(paper_dir: Path) -> dict:
    """Build a summary dict for a single paper directory."""
    name = paper_dir.name
    parts = name.split("_", 2)
    topic = parts[2].replace("_", " ") if len(parts) >= 3 else name

    date_str = ""
    if len(parts) >= 2:
        try:
            d, t = parts[0], parts[1]
            date_str = f"{d[:4]}-{d[4:6]}-{d[6:8]} {t[:2]}:{t[2:4]}"
        except (IndexError, ValueError):
            pass

    info = scan_paper_directory(paper_dir)

    docx_file = info.get("docx_final") or (
        info.get("docx_drafts", [None])[0] if info.get("docx_drafts") else None
    )
    tex_file = info.get("tex_final") or (
        info.get("tex_drafts", [None])[0] if info.get("tex_drafts") else None
    )

    title = None
    word_count = None
    if docx_file:
        title = extract_title_from_docx(docx_file)
        word_count = count_words_in_docx(docx_file)
    elif tex_file:
        title = extract_title_from_tex(tex_file)
        word_count = count_words_in_tex(tex_file)

    has_final = info.get("pdf_final") or info.get("docx_final")
    has_draft = (
        info.get("tex_final")
        or info.get("docx_drafts")
        or info.get("tex_drafts")
    )
    status = "success" if has_final else ("partial" if has_draft else "empty")

    return {
        "name": name,
        "topic": topic,
        "date": date_str,
        "status": status,
        "title": title,
        "word_count": word_count,
        "figures_count": len(info.get("figures", [])),
        "citations_count": count_citations_in_bib(info.get("bibliography")),
    }


@router.get("/status")
async def get_status(request: Request):
    return {
        "model": request.app.state.model,
        "output_folder": str(request.app.state.output_folder),
        "active_tasks": len(request.app.state.active_tasks),
    }


@router.post("/tasks/{task_id}/stop")
async def stop_task(task_id: str, request: Request):
    """Cooperatively cancel a running generation task."""
    task = request.app.state.active_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已结束")
    event = task.get("cancel_event")
    if event is None:
        raise HTTPException(status_code=409, detail="该任务不支持停止")
    event.set()
    task["status"] = "stopping"
    return {"ok": True, "task_id": task_id, "status": "stopping"}


@router.get("/papers")
async def list_papers(request: Request):
    output_folder = request.app.state.output_folder
    papers = find_existing_papers(output_folder)
    return [_paper_summary(p["path"]) for p in papers]


@router.get("/papers/{paper_name}")
async def get_paper(paper_name: str, request: Request):
    output_folder = request.app.state.output_folder
    paper_dir = output_folder / paper_name

    try:
        safe_resolve(paper_dir, output_folder)
    except ValueError:
        raise HTTPException(status_code=403, detail="路径不合法")

    if not paper_dir.is_dir():
        raise HTTPException(status_code=404, detail="文档不存在")

    info = scan_paper_directory(paper_dir)
    summary = _paper_summary(paper_dir)

    summary_content = ""
    if info.get("summary"):
        try:
            summary_content = Path(info["summary"]).read_text(encoding="utf-8")
        except Exception:
            pass

    progress_content = ""
    if info.get("progress_log"):
        try:
            progress_content = Path(info["progress_log"]).read_text(encoding="utf-8")
        except Exception:
            pass

    return {
        **summary,
        "files": {
            "pdf_final": _rel(info.get("pdf_final"), paper_dir),
            "docx_final": _rel(info.get("docx_final"), paper_dir),
            "tex_final": _rel(info.get("tex_final"), paper_dir),
            "pdf_drafts": [_rel(f, paper_dir) for f in info.get("pdf_drafts", [])],
            "docx_drafts": [_rel(f, paper_dir) for f in info.get("docx_drafts", [])],
            "tex_drafts": [_rel(f, paper_dir) for f in info.get("tex_drafts", [])],
            "figures": [_rel(f, paper_dir) for f in info.get("figures", [])],
            "bibliography": _rel(info.get("bibliography"), paper_dir),
            "data": [_rel(f, paper_dir) for f in info.get("data", [])],
            "sources": [_rel(f, paper_dir) for f in info.get("sources", [])],
        },
        "summary_content": summary_content,
        "progress_content": progress_content,
    }


@router.get("/papers/{paper_name}/files/{file_path:path}")
async def serve_file(paper_name: str, file_path: str, request: Request):
    output_folder = request.app.state.output_folder
    paper_dir = output_folder / paper_name

    try:
        safe_resolve(paper_dir, output_folder)
    except ValueError:
        raise HTTPException(status_code=403, detail="路径不合法")

    full_path = paper_dir / file_path
    try:
        safe_resolve(full_path, paper_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="路径不合法")

    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    mime, _ = mimetypes.guess_type(str(full_path))
    if mime is None:
        ext = full_path.suffix.lower()
        mime = {
            ".tex": "text/plain",
            ".bib": "text/plain",
            ".md": "text/plain",
            ".log": "text/plain",
        }.get(ext, "application/octet-stream")

    inline_types = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/svg+xml"}
    disposition = "inline" if mime in inline_types else "attachment"

    return FileResponse(
        path=str(full_path),
        media_type=mime,
        headers={"Content-Disposition": f'{disposition}; filename="{full_path.name}"'},
    )


@router.delete("/papers/{paper_name}")
async def delete_paper(paper_name: str, request: Request):
    output_folder = request.app.state.output_folder
    paper_dir = output_folder / paper_name

    try:
        safe_resolve(paper_dir, output_folder)
    except ValueError:
        raise HTTPException(status_code=403, detail="路径不合法")

    if not paper_dir.is_dir():
        raise HTTPException(status_code=404, detail="文档不存在")

    shutil.rmtree(paper_dir)
    return {"ok": True}


def _rel(path: str | None, base: Path) -> str | None:
    """Convert absolute path to relative path string, using forward slashes."""
    if not path:
        return None
    try:
        return str(Path(path).relative_to(base)).replace("\\", "/")
    except ValueError:
        return None
