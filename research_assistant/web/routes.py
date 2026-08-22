"""REST API routes for papers listing, detail, and file serving."""

import importlib.metadata
import io
import json
import mimetypes
import os
import platform
import shutil
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from ..core import get_api_key, safe_resolve
from ..llm.factory import detect_provider
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

#: B2: events tail-read bounds (first-load default / hard cap).
DEFAULT_TAIL_EVENTS = 500
MAX_TAIL_EVENTS = 2000

#: B6: internal directories excluded from the export zip.
_EXPORT_SKIP_DIRS = {"__pycache__", ".ra"}


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


def _llm_provider() -> str | None:
    """Best-effort provider label derived from config; never exposes the key."""
    try:
        key = get_api_key(None)
    except ValueError:
        return None
    return detect_provider(key, os.getenv("LLM_PROVIDER", ""))


def _base_url_host() -> str | None:
    """Host part of the configured LLM base URL (no key, path, or port)."""
    raw = (os.getenv("LLM_BASE_URL") or "").strip()
    if not raw:
        return None
    return urlsplit(raw).hostname


def _int_env(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("true", "1", "yes")


def _package_version() -> str:
    """版本号以包内 __version__ 为准——冻结环境里 dist-metadata 可能是
    构建机上残留的旧安装（曾把 3.1.0 带进 exe），包内常量才与发布一致。"""
    from .. import __version__

    if __version__:
        return __version__
    try:
        return importlib.metadata.version("research-assistant")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


@router.get("/status")
async def get_status(request: Request):
    return {
        "model": request.app.state.model,
        "output_folder": str(request.app.state.output_folder),
        "active_tasks": len(request.app.state.active_tasks),
        # --- B7 追加的系统信息字段（只增不改） ---
        "provider": _llm_provider(),
        "base_url_host": _base_url_host(),
        "approval_mode": os.getenv("RA_APPROVAL_MODE") or "off",
        "permission_mode": os.getenv("RA_PERMISSION_MODE") or "deny_dangerous",
        "repeat_limit": _int_env("RA_REPEAT_TOOL_LIMIT", 3),
        "pipeline": _bool_env("RA_PIPELINE", True),
        "auto_continue": _bool_env("RA_AUTO_CONTINUE", True),
        "version": _package_version(),
        "python": platform.python_version(),
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


# ---------------------------------------------------------------------------
# Run history (B1) + events tail-read (B2)
# ---------------------------------------------------------------------------

def _safe_run_dir(output_folder: Path, name: str) -> Path:
    """Resolve a run directory name inside *output_folder*, rejecting escapes."""
    if (not name or name in (".", "..") or "/" in name or "\\" in name
            or ":" in name):
        raise ValueError(f"目录名不合法: {name!r}")
    return safe_resolve(output_folder / name, output_folder)


def _load_run_state(paper_dir: Path) -> dict | None:
    """Tolerantly read run.json; ``None`` when missing or corrupt."""
    path = paper_dir / "run.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _run_summary(paper_dir: Path) -> dict:
    """Merge a paper directory summary with its run.json state (B1)."""
    state = _load_run_state(paper_dir)
    stat = paper_dir.stat()
    summary: dict = {
        "name": paper_dir.name,
        "query": "",
        "mode": None,
        "status": "legacy",  # 无（或损坏的）run.json 的旧目录
        "stage": None,
        "stages": {},
        "budget": None,
        "created_at": stat.st_ctime,
        "updated_at": stat.st_mtime,
        "paper": _paper_summary(paper_dir),
    }
    if state is None:
        # legacy：尽力用目录名解析出的 topic 充当查询摘要
        summary["query"] = str(summary["paper"].get("topic") or "")[:200]
        return summary

    budget_full = state.get("budget") or {}
    stages_raw = state.get("stages") or {}
    summary.update({
        "query": str(state.get("query") or "")[:200],
        "mode": state.get("mode") or None,
        # 枚举: running|complete|failed|cancelled（未知值原样透传，消费方需容忍）
        "status": state.get("status") or "running",
        "stage": state.get("stage") or None,
        # 精简为 {阶段名: 状态}，前端时间轴只需要状态
        "stages": {
            name: rec.get("status", "pending")
            for name, rec in stages_raw.items() if isinstance(rec, dict)
        },
        "budget": {
            "cost_usd": budget_full.get("cost_usd"),
            "total_tokens": budget_full.get("total_tokens"),
            "turns": budget_full.get("turns"),
        } if budget_full else None,
        "created_at": state.get("created_at") or stat.st_ctime,
        "updated_at": state.get("updated_at") or stat.st_mtime,
    })
    return summary


@router.get("/runs")
async def list_runs(request: Request):
    """List every paper directory merged with its run.json state, newest first.

    Only direct subdirectories of ``output_folder`` are listed; entries whose
    resolved path would escape it (e.g. symlinks) are skipped.
    """
    output_folder = Path(request.app.state.output_folder)
    runs: list[dict] = []
    if not output_folder.is_dir():
        return runs
    for child in sorted(output_folder.iterdir(), key=lambda p: p.name, reverse=True):
        if not child.is_dir() or child.name.startswith("."):
            continue
        try:
            safe_resolve(child, output_folder)
        except ValueError:
            continue  # 越界条目（符号链接等）直接跳过
        runs.append(_run_summary(child))
    return runs


@router.get("/runs/{run_name}/events")
async def get_run_events(
    run_name: str,
    request: Request,
    after: int = 0,
    tail: int = DEFAULT_TAIL_EVENTS,
):
    """Incremental tail-read of a run's ``events.jsonl`` (B2).

    ``after`` is the number of events the client already holds — only newer
    events are returned. ``tail`` limits first-load size (default 500, capped
    at 2000); incremental reads are capped at the same hard limit so clients
    can catch up in batches. Lines that fail to parse are skipped and ``total``
    counts only parseable events.
    """
    output_folder = Path(request.app.state.output_folder)
    if not output_folder.is_dir():
        raise HTTPException(status_code=404, detail="输出目录不存在")
    try:
        run_dir = _safe_run_dir(output_folder, run_name)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="路径不合法") from exc
    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="运行不存在")

    events_file = run_dir / "events.jsonl"
    parsed: list[dict] = []
    if events_file.is_file():  # 文件不存在时返回空集而非报错
        text = events_file.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # 跳过坏行
            if isinstance(event, dict):
                parsed.append(event)

    total = len(parsed)
    start = max(after, 0)
    if start > 0:
        selected = parsed[start:start + MAX_TAIL_EVENTS]
    else:
        limit = max(min(tail, MAX_TAIL_EVENTS), 0)
        selected = parsed[-limit:] if limit else []
    return {"total": total, "events": selected}


@router.get("/papers/{paper_name}")
async def get_paper(paper_name: str, request: Request):
    output_folder = request.app.state.output_folder
    paper_dir = output_folder / paper_name

    try:
        safe_resolve(paper_dir, output_folder)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="路径不合法") from exc

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
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="路径不合法") from exc

    full_path = paper_dir / file_path
    try:
        safe_resolve(full_path, paper_dir)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="路径不合法") from exc

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


@router.get("/papers/{paper_name}/export")
async def export_paper(paper_name: str, request: Request):
    """Zip the entire paper directory for download (B6).

    Internal ``.ra`` state and ``__pycache__`` directories are excluded.
    """
    output_folder = Path(request.app.state.output_folder)
    if not output_folder.is_dir():
        raise HTTPException(status_code=404, detail="输出目录不存在")
    try:
        paper_dir = _safe_run_dir(output_folder, paper_name)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="路径不合法") from exc
    if not paper_dir.is_dir():
        raise HTTPException(status_code=404, detail="文档不存在")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(paper_dir.rglob("*")):
            rel = path.relative_to(paper_dir)
            if any(part in _EXPORT_SKIP_DIRS for part in rel.parts):
                continue
            if path.is_file():
                zf.write(path, arcname=rel.as_posix())
    zip_name = f"{paper_dir.name}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@router.delete("/papers/{paper_name}")
async def delete_paper(paper_name: str, request: Request):
    output_folder = request.app.state.output_folder
    paper_dir = output_folder / paper_name

    try:
        safe_resolve(paper_dir, output_folder)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="路径不合法") from exc

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
