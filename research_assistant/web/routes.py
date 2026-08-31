"""REST API routes for papers listing, detail, and file serving."""

import asyncio
import importlib.metadata
import io
import json
import logging
import mimetypes
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from ..config import research_os_enabled, resolve_model
from ..core import get_api_key, safe_resolve
from ..llm.factory import detect_provider
from ..runtime.analysis import runtime_environment, schema_changes, snapshot_input_files
from ..utils import (
    count_citations_in_bib,
    count_words_in_docx,
    count_words_in_tex,
    extract_title_from_docx,
    extract_title_from_tex,
    find_existing_papers,
    scan_paper_directory,
)
from ..workflows import get_workflow_registry

router = APIRouter()

LOG = logging.getLogger(__name__)

#: B2: events tail-read bounds (first-load default / hard cap).
DEFAULT_TAIL_EVENTS = 500
MAX_TAIL_EVENTS = 2000

#: B6: internal directories excluded from the export zip.
_EXPORT_SKIP_DIRS = {"__pycache__", ".ra"}

_SCHEDULER_PAYLOAD_KEYS = {
    "query", "model", "provider", "output_dir", "data_files",
    "max_cost_usd", "max_wall_seconds", "rerun_step",
}

_ARTIFACT_TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".py", ".js", ".ts", ".tsx", ".json",
    ".csv", ".tsv", ".bib", ".log", ".yaml", ".yml", ".tex", ".html", ".htm",
    ".css", ".scss", ".xml", ".toml", ".ini", ".cfg", ".conf", ".sh", ".bat",
    ".ps1", ".sql",
}


def _safe_scheduler_payload(value: object) -> dict:
    """Keep queue payloads declarative and prevent credentials being persisted."""
    if not isinstance(value, dict):
        return {}
    result: dict = {}
    for key in _SCHEDULER_PAYLOAD_KEYS:
        item = value.get(key)
        if item is None:
            continue
        if key == "data_files":
            if isinstance(item, list):
                result[key] = [str(path)[:500] for path in item[:100] if str(path).strip()]
            continue
        if key in {"max_cost_usd", "max_wall_seconds"}:
            try:
                number = float(item)
            except (TypeError, ValueError):
                continue
            if number > 0:
                result[key] = number
            continue
        if key == "rerun_step":
            result[key] = str(item)[:128]
            continue
        result[key] = str(item)[:4000]
    return result


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
            pass  # 尽力而为：目录名日期段不规范时留空，不影响其余摘要字段

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
    live = getattr(request.app.state, "task_hub", None)
    live_count = sum(
        1 for handle in getattr(live, "handles", {}).values()
        if handle.status in {"queued", "running", "stopping"}
    )
    return {
        # 实时解析而非 lifespan 快照：设置页保存后免刷新即反映（R7 反馈 #2）
        "model": resolve_model(None),
        "model_profiles": {
            "default": resolve_model(None),
            "fast": os.environ.get("RA_MODEL_FAST") or resolve_model(None),
            "strong": os.environ.get("RA_MODEL_STRONG") or resolve_model(None),
        },
        "output_folder": str(request.app.state.output_folder),
        "active_tasks": live_count,
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
        "research_os": research_os_enabled(),
    }


@router.get("/project/home")
async def get_project_home(request: Request):
    """Unified project-space landing payload."""
    store = request.app.state.platform_store
    return await asyncio.to_thread(store.project_home, request.app.state.project["id"])


@router.get("/project/usage")
async def get_project_usage(request: Request):
    store = request.app.state.platform_store
    return await asyncio.to_thread(store.resource_usage, request.app.state.project["id"])


@router.get("/notifications")
async def list_project_notifications(request: Request, unread_only: bool = False, limit: int = 100):
    store = request.app.state.platform_store
    return await asyncio.to_thread(store.list_notifications, request.app.state.project["id"], unread_only=unread_only, limit=limit)


@router.post("/notifications/{notification_id}/read")
async def mark_project_notification_read(notification_id: str, request: Request):
    store = request.app.state.platform_store
    ok = await asyncio.to_thread(store.mark_notification_read, notification_id, request.app.state.project["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="通知不存在")
    return {"ok": True}


@router.get("/approvals")
async def list_project_approvals(request: Request, status: str | None = "pending", limit: int = 100):
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.list_agent_approvals, project_id, status=status, limit=limit)


@router.post("/approvals/{approval_id}/resolve")
async def resolve_project_approval(approval_id: str, request: Request):
    body = await request.json()
    approved = bool((body or {}).get("approved"))
    note = str((body or {}).get("note") or "")
    store, project_id = _research_store(request)
    approvals = await asyncio.to_thread(store.list_agent_approvals, project_id, status="pending", limit=500)
    item = next((row for row in approvals if str(row.get("id")) == approval_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="审批请求不存在或已处理")
    hub = getattr(request.app.state, "task_hub", None)
    if hub is None or not hub.approve(str(item.get("task_id") or ""), approved, approval_id, note):
        raise HTTPException(status_code=409, detail="对应 Agent 已不在可接管状态，请刷新审批队列")
    resolved = await asyncio.to_thread(store.resolve_agent_approval, approval_id, project_id, approved=approved, note=note)
    return resolved or {"id": approval_id, "status": "resolved"}


def _build_project_export_bytes(root: Path, manifest: dict, sources: list) -> bytes:
    """内存打包工作区导出包（同步重 IO，由端点经线程池调用）。

    Internal databases, caches, VCS metadata and dotenv files are excluded;
    their decoded project records are represented in ``research_manifest.json``.
    """
    buf = io.BytesIO()
    excluded = {".ra", ".git", "__pycache__", "node_modules", ".pytest_cache", ".mypy_cache", "build", "dist"}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("research_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("sources.json", json.dumps(sources, ensure_ascii=False, indent=2))
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if any(part in excluded or part.startswith(".") for part in rel.parts):
                continue
            if path.name.lower() in {".env", ".env.local", ".env.production", ".env.development"} or path.name.startswith(".env."):
                continue
            zf.write(path, arcname=f"workspace/{rel.as_posix()}")
    return buf.getvalue()


@router.get("/project/export")
async def export_project(request: Request):
    """Export a portable research package (artifacts + auditable manifest)."""
    store = request.app.state.platform_store
    project_id = request.app.state.project["id"]
    manifest = await asyncio.to_thread(store.export_project_manifest, project_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="项目不存在")
    source_store = getattr(request.app.state, "source_store", None)
    sources = await asyncio.to_thread(source_store.list_sources, limit=1000) if source_store is not None else []
    root = _project_root(request)
    # rglob + zip 压缩是同步重 IO，放线程池避免卡死事件循环
    payload = await asyncio.to_thread(_build_project_export_bytes, root, manifest, sources)
    name = str((manifest.get("project") or {}).get("name") or root.name).replace("/", "_").replace("\\", "_")
    return Response(content=payload, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}.research.zip"'})


#: 研究包导入的解压上限（P0-6：zip bomb 防护）。
#:
#: 此前只校验**压缩包原始体积** ≤1GB，随后逐条解压写盘却从不检查解压后
#: 体积——一个 1MB 的 zip bomb 足以打满磁盘。两道闸：
#:   1. 解压前按 ZipInfo.file_size 预检（主闸，此时尚未落盘，不会留残骸）；
#:   2. 写盘前按实际读出的字节数复核（兜底，防 file_size 字段撒谎）。
#: 不做中途回滚：冲突策略可能是 overwrite，回滚删除会误伤用户既有文件。
MAX_IMPORT_UNCOMPRESSED_BYTES = 2 * 1024**3  # 解压后总量 2GB
MAX_IMPORT_SINGLE_FILE_BYTES = 1024**3       # 单文件 1GB


@router.post("/project/import")
async def import_project(request: Request, overwrite: bool | None = None, conflict: str = "skip"):
    """Merge a package with explicit skip/overwrite/rename conflict semantics."""
    if overwrite is not None:
        conflict = "overwrite" if overwrite else "skip"
    if conflict not in {"skip", "overwrite", "rename"}:
        raise HTTPException(status_code=422, detail="conflict 必须是 skip、overwrite 或 rename")
    raw = await request.body()
    if len(raw) > 1024 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="研究包过大")
    root = _project_root(request)
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail="不是有效的研究包") from exc
    imported: list[str] = []
    conflicts: list[str] = []
    excluded = {".ra", ".git", "__pycache__", "node_modules", "build", "dist"}
    try:
        safe_entries: list[tuple[zipfile.ZipInfo, Path]] = []
        total_uncompressed = 0
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if not name.startswith("workspace/") or name.endswith("/"):
                continue
            rel = Path(name.removeprefix("workspace/"))
            if rel.is_absolute() or ".." in rel.parts or any(part in excluded or part.startswith(".") for part in rel.parts):
                raise HTTPException(status_code=422, detail="研究包包含不安全路径")
            # 解压前预检：此刻一个字节都还没落盘，超限即整包拒绝
            if info.file_size > MAX_IMPORT_SINGLE_FILE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"单个文件解压后超过 {MAX_IMPORT_SINGLE_FILE_BYTES // 1024**3}GB：{rel.as_posix()}",
                )
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_IMPORT_UNCOMPRESSED_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"研究包解压后总量超过 {MAX_IMPORT_UNCOMPRESSED_BYTES // 1024**3}GB"
                        "（疑似压缩包炸弹），已拒绝导入且未写入任何文件"
                    ),
                )
            safe_entries.append((info, rel))
        manifest: dict = {}
        try:
            decoded = json.loads(archive.read("research_manifest.json").decode("utf-8"))
            if isinstance(decoded, dict):
                manifest = decoded
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
            pass  # 合理降级：清单文件缺失或损坏时按无 manifest 导入（不阻断包导入）
        imported_rows = await asyncio.to_thread(
            request.app.state.platform_store.import_project_manifest,
            request.app.state.project["id"], manifest,
        ) if manifest else {}
        written_uncompressed = 0
        for info, rel in safe_entries:
            target = safe_resolve(root / rel, root)
            if target.exists():
                conflicts.append(rel.as_posix())
                if conflict == "skip":
                    continue
                if conflict == "rename":
                    stem, suffix = target.stem, target.suffix
                    index = 1
                    while target.exists():
                        target = target.with_name(f"{stem}.import-{index}{suffix}")
                        index += 1
            target.parent.mkdir(parents=True, exist_ok=True)
            # 写盘前按实际字节数复核：file_size 来自 zip 元数据，可以被伪造
            data = archive.read(info)
            if len(data) > MAX_IMPORT_SINGLE_FILE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"单个文件解压后超过上限（实际 {len(data)} 字节）：{rel.as_posix()}",
                )
            written_uncompressed += len(data)
            if written_uncompressed > MAX_IMPORT_UNCOMPRESSED_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="研究包解压后总量超过上限（疑似压缩包炸弹），导入已中止",
                )
            target.write_bytes(data)
            imported.append(rel.as_posix())
    finally:
        archive.close()
    return {"ok": True, "imported": imported, "conflicts": conflicts, "conflict_strategy": conflict, "imported_rows": imported_rows, "skipped_existing": conflict == "skip"}


@router.get("/threads")
async def list_threads(request: Request, limit: int = 100, include_archived: bool = False):
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.list_threads, project_id, limit=limit, include_archived=include_archived)


@router.post("/threads")
async def create_thread(request: Request):
    body = await request.json()
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.create_thread, project_id=project_id, title=str((body or {}).get("title") or "新研究线程"), kind=str((body or {}).get("kind") or "agent"), context_summary=str((body or {}).get("context_summary") or ""), metadata=body.get("metadata") if isinstance(body, dict) and isinstance(body.get("metadata"), dict) else {})


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str, request: Request):
    store, project_id = _research_store(request)
    thread = await asyncio.to_thread(store.get_thread, thread_id, project_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="线程不存在")
    thread["items"] = await asyncio.to_thread(store.list_thread_items, thread_id, limit=1000)
    return thread


@router.post("/threads/{thread_id}/fork")
async def fork_thread(thread_id: str, request: Request):
    body = await request.json()
    store, project_id = _research_store(request)
    try:
        return await asyncio.to_thread(store.fork_thread, thread_id, project_id=project_id, title=str((body or {}).get("title") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/threads/{thread_id}/archive")
async def archive_thread(thread_id: str, request: Request):
    store, project_id = _research_store(request)
    if not await asyncio.to_thread(store.archive_thread, thread_id, project_id=project_id):
        raise HTTPException(status_code=404, detail="线程不存在")
    return {"ok": True}


@router.get("/research/quality/items")
async def list_research_quality_items(request: Request, status: str | None = None, limit: int = 200):
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.list_quality_items, project_id, status=status, limit=limit)


@router.get("/artifacts/reviews")
async def list_artifact_reviews(request: Request, status: str | None = None, limit: int = 200):
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.list_artifact_reviews, project_id, status=status, limit=limit)


def _project_root(request: Request) -> Path:
    project = getattr(request.app.state, "project", {}) or {}
    return Path(str(project.get("root") or request.app.state.cwd)).resolve()


async def _artifact_review_or_404(review_id: str, request: Request) -> tuple[object, dict, Path]:
    store, project_id = _research_store(request)
    review = await asyncio.to_thread(store.get_artifact_review, review_id, project_id)
    if review is None:
        raise HTTPException(status_code=404, detail="产物审阅记录不存在")
    root = _project_root(request)
    try:
        target = safe_resolve(root / str(review.get("artifact_path") or ""), root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="产物路径越界，拒绝访问") from exc
    return store, review, target


@router.get("/artifacts/reviews/{review_id}")
async def get_artifact_review(review_id: str, request: Request):
    store, review, _ = await _artifact_review_or_404(review_id, request)
    project_id = request.app.state.project["id"]
    return {
        "review": review,
        "provenance": await asyncio.to_thread(store.list_provenance, project_id, object_type="artifact_review", object_id=review_id),
        "quality_items": await asyncio.to_thread(store.list_quality_items, project_id, object_type="artifact", object_id=review_id, limit=100),
    }


@router.get("/artifacts/reviews/{review_id}/provenance")
async def get_artifact_review_provenance(review_id: str, request: Request):
    store, _, _ = await _artifact_review_or_404(review_id, request)
    return await asyncio.to_thread(
        store.list_provenance, request.app.state.project["id"],
        object_type="artifact_review", object_id=review_id,
    )


@router.get("/artifacts/reviews/{review_id}/preview")
async def preview_artifact_review(review_id: str, request: Request):
    _, review, target = await _artifact_review_or_404(review_id, request)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="产物文件不存在")
    size = target.stat().st_size
    suffix = target.suffix.lower()
    if suffix in _ARTIFACT_TEXT_EXTENSIONS or suffix == "":
        data = target.read_bytes()[:256 * 1024]
        return {
            "kind": "text", "path": review["artifact_path"],
            "content": data.decode("utf-8", errors="replace"),
            "truncated": size > len(data), "size": size,
        }
    mime, _ = mimetypes.guess_type(str(target))
    return {
        "kind": "binary", "path": review["artifact_path"], "size": size,
        "mime": mime or "application/octet-stream",
        "url": f"/api/workspace/file?path={quote(str(review['artifact_path']), safe='')}",
    }


@router.get("/artifacts/reviews/{review_id}/diff")
async def diff_artifact_review(review_id: str, request: Request):
    _, review, _ = await _artifact_review_or_404(review_id, request)
    from ..artifacts import ArtifactVersionStore
    versions = ArtifactVersionStore(_project_root(request)).list(limit=1000)
    changes = [item for item in versions if item.get("path") == review.get("artifact_path")]
    result = []
    for item in changes[:20]:
        try:
            result.append(ArtifactVersionStore(_project_root(request)).diff(str(item["id"])))
        except (KeyError, OSError):
            continue
    return {"artifact_path": review.get("artifact_path"), "version": review.get("version"), "changes": result}


@router.post("/artifacts/reviews/{review_id}/request-changes")
async def request_artifact_changes(review_id: str, request: Request):
    body = await request.json()
    store, review, _ = await _artifact_review_or_404(review_id, request)
    project_id = request.app.state.project["id"]
    comment = str((body or {}).get("comment") or review.get("comment") or "请根据审阅意见修改此产物").strip()
    updated = await asyncio.to_thread(
        store.review_artifact, project_id=project_id,
        artifact_path=str(review["artifact_path"]), version=int(review.get("version") or 1),
        status="needs_changes", comment=comment,
        task_id=review.get("task_id"), run_id=review.get("run_id"), thread_id=review.get("thread_id"),
        metadata=review.get("metadata") if isinstance(review.get("metadata"), dict) else {},
    )
    note = await asyncio.to_thread(
        store.create_notification, project_id=project_id, kind="artifact_changes_requested",
        title="产物需要修改", message=f"{review['artifact_path']} v{review.get('version', 1)}：{comment}",
        object_type="artifact_review", object_id=review_id,
    )
    thread_id = review.get("thread_id")
    item = None
    if thread_id:
        item = await asyncio.to_thread(
            store.append_agent_item, thread_id=str(thread_id), project_id=project_id,
            item_type="approval", title="产物修改请求",
            content={"review_id": review_id, "artifact_path": review["artifact_path"], "comment": comment},
            status="pending",
        )
    return {"review": updated, "notification": note, "agent_item": item}


@router.post("/artifacts/reviews")
async def review_artifact(request: Request):
    body = await request.json()
    path = str((body or {}).get("artifact_path") or "").strip()
    if not path:
        raise HTTPException(status_code=422, detail="artifact_path 不能为空")
    store, project_id = _research_store(request)
    try:
        return await asyncio.to_thread(store.review_artifact, project_id=project_id, artifact_path=path, status=str(body.get("status") or "pending"), comment=str(body.get("comment") or ""), task_id=body.get("task_id"), run_id=body.get("run_id"), thread_id=body.get("thread_id"), version=int(body.get("version") or 1), metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else {})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/workflows")
async def list_workflows():
    """List safe, declarative multi-agent workflows available to the UI."""
    return get_workflow_registry().list_workflows()


@router.post("/tasks/{task_id}/stop")
async def stop_task(task_id: str, request: Request):
    """Cooperatively cancel a running generation task."""
    hub = getattr(request.app.state, "task_hub", None)
    if hub is not None and hub.stop(task_id):
        return {"ok": True, "task_id": task_id, "status": "stopping"}
    # Legacy in-process task registry used by minimal/test app setups.
    legacy_tasks = getattr(request.app.state, "active_tasks", None) or {}
    legacy = legacy_tasks.get(task_id)
    if legacy is None:
        raise HTTPException(status_code=404, detail="任务不存在或已结束")
    cancel_event = legacy.get("cancel_event")
    if not isinstance(cancel_event, asyncio.Event):
        raise HTTPException(status_code=409, detail="任务不可停止：缺少取消句柄")
    cancel_event.set()
    legacy["status"] = "stopping"
    return {"ok": True, "task_id": task_id, "status": "stopping"}


@router.get("/tasks")
async def list_platform_tasks(request: Request, limit: int = 100):
    """List durable tasks for the active research project."""
    store = request.app.state.platform_store
    project = request.app.state.project
    return await asyncio.to_thread(store.list_tasks, project_id=project["id"], limit=limit)


@router.get("/tasks/{task_id}/plan")
async def get_task_plan(task_id: str, request: Request):
    """Return the durable workflow DAG plus per-node lifecycle state."""
    store = request.app.state.platform_store
    task = await asyncio.to_thread(store.get_task, task_id)
    if task is None or task["project_id"] != request.app.state.project["id"]:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"task_id": task_id, "steps": await asyncio.to_thread(store.list_steps, task_id)}


@router.post("/tasks/{task_id}/steps/{step_id}/rerun")
async def rerun_task_step(task_id: str, step_id: str, request: Request):
    """Queue a precise generic-workflow node rerun without mutating history."""
    store = request.app.state.platform_store
    project_id = request.app.state.project["id"]
    task = await asyncio.to_thread(store.get_task, task_id)
    if task is None or task.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.get("status") in {"queued", "running", "stopping"}:
        raise HTTPException(status_code=409, detail="任务仍在运行，不能重跑节点")
    metadata = task.get("metadata") or {}
    workflow_id = str(metadata.get("workflow_id") or "")
    if workflow_id in {"", "single", "paper"}:
        raise HTTPException(status_code=409, detail="当前任务没有可单独重跑的通用 Agent 节点")
    steps = await asyncio.to_thread(store.list_steps, task_id)
    if not any(str(step.get("id")) == step_id for step in steps):
        raise HTTPException(status_code=404, detail="工作流节点不存在")
    payload = _safe_scheduler_payload({
        "query": task.get("query"), "output_dir": task.get("output_dir"),
        "rerun_step": step_id,
    })
    job = await asyncio.to_thread(
        store.enqueue_job, project_id=project_id, workflow_id=workflow_id,
        payload=payload, max_attempts=3,
    )
    return {"ok": True, "job": job, "rerun_step": step_id, "workflow_id": workflow_id}


async def _control_task_step(task_id: str, step_id: str, request: Request, *, status: str, title: str):
    store = request.app.state.platform_store
    project_id = request.app.state.project["id"]
    task = await asyncio.to_thread(store.get_task, task_id)
    if task is None or task.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.get("status") in {"queued", "running", "stopping"}:
        raise HTTPException(status_code=409, detail="任务仍在运行，请先停止后再人工控制节点")
    steps = await asyncio.to_thread(store.list_steps, task_id)
    if not any(str(step.get("id")) == step_id for step in steps):
        raise HTTPException(status_code=404, detail="工作流节点不存在")
    await asyncio.to_thread(store.update_step, task_id, step_id, status=status)
    metadata = task.get("metadata") or {}
    item = None
    if metadata.get("thread_id"):
        item = await asyncio.to_thread(
            store.append_agent_item, thread_id=str(metadata["thread_id"]), project_id=project_id,
            turn_id=str(metadata.get("turn_id") or "") or None, item_type="status", title=title,
            content={"task_id": task_id, "step_id": step_id, "status": status, "human_controlled": True},
            status="complete",
        )
    return {"ok": True, "task_id": task_id, "step_id": step_id, "status": status, "agent_item": item}


@router.post("/tasks/{task_id}/steps/{step_id}/skip")
async def skip_task_step(task_id: str, step_id: str, request: Request):
    return await _control_task_step(task_id, step_id, request, status="skipped", title="人工跳过 Agent 节点")


@router.post("/tasks/{task_id}/steps/{step_id}/takeover")
async def takeover_task_step(task_id: str, step_id: str, request: Request):
    return await _control_task_step(task_id, step_id, request, status="done", title="人工接管 Agent 节点")


@router.get("/tasks/{task_id}/metrics")
async def get_task_metrics(task_id: str, request: Request):
    """Return task timing and event metrics for performance diagnosis."""
    store = request.app.state.platform_store
    task = await asyncio.to_thread(store.get_task, task_id)
    if task is None or task["project_id"] != request.app.state.project["id"]:
        raise HTTPException(status_code=404, detail="任务不存在")
    return await asyncio.to_thread(store.task_metrics, task_id)


@router.get("/tasks/{task_id}/agents")
async def get_task_agents(task_id: str, request: Request):
    """Return a compact, inspectable Agent roster for the task detail panel."""
    store = request.app.state.platform_store
    project_id = request.app.state.project["id"]
    task = await asyncio.to_thread(store.get_task, task_id)
    if task is None or task.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    metadata = task.get("metadata") or {}
    workflow_id = str(metadata.get("workflow_id") or "")
    workflow = None
    if workflow_id:
        try:
            workflow = get_workflow_registry().get_workflow(workflow_id)
        except KeyError:
            workflow = None
    steps = await asyncio.to_thread(store.list_steps, task_id)
    persisted_runs = await asyncio.to_thread(store.list_agent_runs, project_id, task_id=task_id, limit=100)
    role_by_step = {step.id: step.role for step in (workflow.steps if workflow else ())}
    role_titles = {}
    if workflow:
        registry = get_workflow_registry()
        role_titles = {step.role: registry.get_role(step.role).title for step in workflow.steps}
    agents = []
    run_by_agent = {str(item.get("agent_id")): item for item in persisted_runs}
    for step in steps:
        role = role_by_step.get(str(step.get("id")), "")
        started, finished = step.get("started_at"), step.get("finished_at")
        seconds = None if started is None else round(max(0.0, (finished or time.time()) - started), 3)
        run = run_by_agent.get(str(step.get("id")), {})
        agents.append({
            "agent_id": step.get("id"), "role": role, "role_title": role_titles.get(role, role),
            "title": step.get("title"), "status": step.get("status"), "error": step.get("error") or "",
            "seconds": seconds, "started_at": started, "finished_at": finished,
            "budget": run.get("budget") or {}, "outputs": run.get("outputs") or {},
        })
    thread_id = metadata.get("thread_id")
    items = await asyncio.to_thread(store.list_thread_items, str(thread_id), limit=500) if thread_id else []
    return {"task_id": task_id, "workflow_id": workflow_id, "status": task.get("status"), "agents": agents, "items": items[-100:]}


@router.get("/agent-runs")
async def list_agent_runs(request: Request, task_id: str | None = None, limit: int = 200):
    store, project_id = _research_store(request)
    if task_id:
        task = await asyncio.to_thread(store.get_task, task_id)
        if task is None or task.get("project_id") != project_id:
            raise HTTPException(status_code=404, detail="任务不存在")
    return await asyncio.to_thread(store.list_agent_runs, project_id, task_id=task_id, limit=limit)


@router.post("/sources/upload")
async def upload_source(request: Request):
    """Ingest PDF/DOCX/MD/TXT into the project source library (FTS5)."""
    store = getattr(request.app.state, "source_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="资料库不可用")
    content_type = request.headers.get("content-type", "")
    saved: list[dict] = []
    replaced_source_ids: list[str] = []
    platform_store = getattr(request.app.state, "platform_store", None)
    project_id = getattr(request.app.state, "project", {}).get("id") if platform_store is not None else None

    async def ingest_with_change_tracking(path: Path, *, name: str | None = None) -> dict:
        if name and platform_store is not None and project_id:
            existing = await asyncio.to_thread(store.list_sources, limit=500)
            for source_row in existing:
                if str(source_row.get("name") or "") == name:
                    await asyncio.to_thread(platform_store.mark_source_stale, project_id=project_id, source_id=str(source_row["id"]), reason="资料已重新导入，原证据需要复审")
                    replaced_source_ids.append(str(source_row["id"]))
        return await asyncio.to_thread(store.ingest_file, path, name=name)
    if "multipart/form-data" in content_type:
        form = await request.form()
        allowed = {".pdf", ".docx", ".md", ".txt", ".bib"}
        # Starlette returns ``starlette.datastructures.UploadFile`` instances;
        # checking the upload protocol keeps this compatible with FastAPI's
        # subclass and with lightweight test clients.
        uploads = [v for v in form.values() if hasattr(v, "filename") and hasattr(v, "read")]
        for up in uploads:
            suffix = Path(up.filename or "").suffix.lower()
            if suffix not in allowed:
                raise HTTPException(
                    status_code=415,
                    detail=f"不支持的类型 {suffix}（支持 pdf/docx/md/txt/bib）",
                )
            data = await up.read()
            if len(data) > 50 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="文件过大（>50MB）")
            tmp_dir = request.app.state.cwd / ".ra" / "uploads"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            target = tmp_dir / f"{uuid.uuid4().hex}{suffix}"
            target.write_bytes(data)
            try:
                saved.append(await ingest_with_change_tracking(target, name=up.filename))
            finally:
                target.unlink(missing_ok=True)
    else:
        body = await request.json()
        path = str((body or {}).get("path") or "")
        root = Path(str(request.app.state.cwd))
        resolved = safe_resolve(root / path if not Path(path).is_absolute() else Path(path), root)
        if not resolved.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        saved.append(await ingest_with_change_tracking(resolved, name=resolved.name))
    return {"ok": True, "sources": saved, "replaced_source_ids": replaced_source_ids}


@router.get("/sources")
async def list_sources(request: Request, limit: int = 100):
    store = getattr(request.app.state, "source_store", None)
    if store is None:
        return []
    return await asyncio.to_thread(store.list_sources, limit=limit)


@router.get("/sources/search")
async def search_sources(
    request: Request,
    q: str,
    limit: int = 8,
    mode: str = "hybrid",
):
    """Hybrid source search with stable anchors (file/page/chunk/hash)."""
    store = getattr(request.app.state, "source_store", None)
    if store is None:
        return []
    return await asyncio.to_thread(store.search, q, limit=limit, mode=mode)


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str, request: Request):
    store = getattr(request.app.state, "source_store", None)
    if store is None or not await asyncio.to_thread(store.delete_source, source_id):
        raise HTTPException(status_code=404, detail="资料不存在")
    platform_store, project_id = _research_store(request)
    impact = await asyncio.to_thread(platform_store.mark_source_stale, project_id=project_id, source_id=source_id)
    return {"ok": True, "source_id": source_id, "impact": impact}


@router.get("/project/instructions")
async def get_project_instructions(request: Request):
    """Long-term project instructions injected into every pipeline agent."""
    project = request.app.state.project
    return {"instructions": str(project.get("instructions") or "")}


@router.put("/project/instructions")
async def put_project_instructions(request: Request):
    body = await request.json()
    text = str((body or {}).get("instructions") or "")
    if len(text) > 20_000:
        raise HTTPException(status_code=413, detail="项目指令过长（最大 20000 字符）")
    store = request.app.state.platform_store
    project = request.app.state.project
    updated = store.update_project_instructions(project["id"], instructions=text)
    if updated is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    request.app.state.project = updated
    return {"ok": True, "instructions": str(updated.get("instructions") or "")}


@router.get("/tasks/{task_id}")
async def get_platform_task(task_id: str, request: Request):
    task = await asyncio.to_thread(request.app.state.platform_store.get_task, task_id)
    if task is None or task["project_id"] != request.app.state.project["id"]:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


# ---------------------------------------------------------------------------
# Research OS object graph
# ---------------------------------------------------------------------------

def _research_store(request: Request):
    store = getattr(request.app.state, "platform_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="科研对象库不可用")
    return store, request.app.state.project["id"]


@router.get("/research/overview")
async def research_overview(request: Request):
    """只读统一视图：科研对象计数 + 工作区级快照（会话/任务/作业/产物/事件）。

    计划项 3.6：给前端一个稳定读法。纯只读聚合——不触发任何清退、
    不新增写入路径；原 research_overview 的 counts/uncovered_claims
    键保持不变，工作区快照以新增键合并进同一响应。
    """
    store, project_id = _research_store(request)
    base = await asyncio.to_thread(store.research_overview, project_id)
    base.update(await asyncio.to_thread(_workspace_snapshot, request, store, project_id))
    return base


def _workspace_snapshot(request: Request, store, project_id: str) -> dict:
    """聚合工作区级只读快照（全部走既有查询方法与只读 SQL）。"""
    snapshot: dict[str, Any] = {}

    # ---- 会话列表摘要：复用 chat.py 的会话目录摘要（不触发清退）----
    from .chat import _load_run_state, _session_summary, _sessions_root

    cwd = getattr(request.app.state, "cwd", None) or Path.cwd()
    root = _sessions_root(cwd)
    sessions: list[dict[str, Any]] = []
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if _load_run_state(child) is None:
                continue  # 无 run.json 的杂散目录不算会话
            try:
                sessions.append(_session_summary(child))
            except OSError:
                continue  # 并发删除等竞态：跳过即可
    sessions.sort(key=lambda s: -(s.get("updated_at") or 0))
    snapshot["sessions"] = {
        "total": len(sessions),
        "recent": sessions[:20],
    }

    # ---- 任务计数与最近状态 ----
    tasks = store.list_tasks(project_id, limit=200)
    task_status_counts: dict[str, int] = {}
    for t in tasks:
        status = str(t.get("status") or "unknown")
        task_status_counts[status] = task_status_counts.get(status, 0) + 1
    snapshot["tasks"] = {
        "total": len(tasks),
        "by_status": task_status_counts,
        "recent": [
            {
                "id": t.get("id"),
                "title": t.get("title") or t.get("query") or "",
                "status": t.get("status"),
                "created_at": t.get("created_at"),
                "updated_at": t.get("updated_at"),
            }
            for t in tasks[:5]
        ],
    }

    # ---- 作业计数与最近状态 ----
    jobs = store.list_jobs(project_id, limit=200)
    job_status_counts: dict[str, int] = {}
    for j in jobs:
        status = str(j.get("status") or "unknown")
        job_status_counts[status] = job_status_counts.get(status, 0) + 1
    snapshot["jobs"] = {
        "total": len(jobs),
        "by_status": job_status_counts,
        "recent": [
            {
                "id": j.get("id"),
                "workflow_id": j.get("workflow_id"),
                "status": j.get("status"),
                "attempts": j.get("attempts"),
                "updated_at": j.get("updated_at"),
                "last_error": j.get("last_error") or "",
            }
            for j in jobs[:5]
        ],
    }

    # ---- 产物计数（artifacts 表）与最近事件 ----
    snapshot["artifacts"] = store.artifacts_overview()
    snapshot["recent_events"] = store.recent_project_events(project_id, limit=10)
    return snapshot


@router.get("/research/quality")
async def research_quality(request: Request):
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.research_quality_report, project_id)


@router.get("/research/evidence-matrix")
async def research_evidence_matrix(request: Request, limit: int = 300):
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.evidence_matrix, project_id, limit=limit)


@router.patch("/research/claims/{claim_id}")
async def update_research_claim(claim_id: str, request: Request):
    body = await request.json()
    store, project_id = _research_store(request)
    try:
        claim = await asyncio.to_thread(store.update_claim, claim_id, project_id=project_id, status=body.get("status"), confidence=body.get("confidence"), text=body.get("text"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if claim is None:
        raise HTTPException(status_code=404, detail="主张不存在")
    return claim


@router.get("/project/search")
async def search_project(request: Request, q: str, limit: int = 30):
    store, project_id = _research_store(request)
    results = await asyncio.to_thread(store.search_project, project_id, q, limit=limit)
    source_store = getattr(request.app.state, "source_store", None)
    if source_store is not None and str(q).strip():
        source_hits = await asyncio.to_thread(source_store.search, str(q), limit=max(1, min(int(limit), 30)), mode="hybrid")
        results.extend({
            "kind": "source", "id": hit.get("source_id") or hit.get("anchor", {}).get("source_id"),
            "title": hit.get("file") or hit.get("anchor", {}).get("file") or "资料",
            "detail": hit.get("snippet") or hit.get("text") or "", "updated_at": 0,
        } for hit in source_hits if isinstance(hit, dict))
    return sorted(results, key=lambda item: float(item.get("updated_at") or 0), reverse=True)[:max(1, min(int(limit), 100))]


@router.get("/project/activity")
async def project_activity(request: Request, after: float = 0.0,
                           cursor: str | None = None, limit: int = 100):
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.project_activity, project_id, after=after, cursor=cursor, limit=limit)


@router.get("/research/items")
async def list_research_items(request: Request, kind: str | None = None, limit: int = 200):
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.list_research_items, project_id, kind=kind, limit=limit)


@router.post("/research/items")
async def create_research_item(request: Request):
    body = await request.json()
    if not isinstance(body, dict) or not str(body.get("title") or "").strip():
        raise HTTPException(status_code=422, detail="title 不能为空")
    store, project_id = _research_store(request)
    try:
        return await asyncio.to_thread(
            store.create_research_item, project_id=project_id, kind=str(body.get("kind") or "note"),
            title=str(body["title"]), body=str(body.get("body") or ""), status=str(body.get("status") or "open"),
            metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/research/items/{item_id}")
async def update_research_item(item_id: str, request: Request):
    body = await request.json()
    store, project_id = _research_store(request)
    existing = await asyncio.to_thread(store.list_research_items, project_id, limit=1000)
    if not any(str(item.get("id")) == item_id for item in existing):
        raise HTTPException(status_code=404, detail="研究对象不存在")
    return await asyncio.to_thread(store.update_research_item, item_id, title=body.get("title"), body=body.get("body"), status=body.get("status"), metadata=body.get("metadata"))


@router.get("/research/claims")
async def list_research_claims(request: Request, limit: int = 200):
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.list_claims, project_id, limit=limit)


@router.post("/research/claims")
async def create_research_claim(request: Request):
    body = await request.json()
    if not isinstance(body, dict) or not str(body.get("text") or "").strip():
        raise HTTPException(status_code=422, detail="text 不能为空")
    store, project_id = _research_store(request)
    try:
        return await asyncio.to_thread(store.create_claim, project_id=project_id, text=str(body["text"]), status=str(body.get("status") or "proposed"), confidence=body.get("confidence"), metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else {})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/research/evidence")
async def list_research_evidence(request: Request, claim_id: str | None = None, limit: int = 300):
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.list_evidence, project_id, claim_id=claim_id, limit=limit)


@router.post("/research/evidence")
async def create_research_evidence(request: Request):
    body = await request.json()
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.create_evidence, project_id=project_id, source_id=body.get("source_id"), source_anchor=str(body.get("source_anchor") or ""), excerpt=str(body.get("excerpt") or ""), artifact_path=body.get("artifact_path"), kind=str(body.get("kind") or "source"), metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else {})


@router.post("/research/claims/{claim_id}/evidence")
async def link_research_evidence(claim_id: str, request: Request):
    body = await request.json()
    evidence_id = str((body or {}).get("evidence_id") or "")
    if not evidence_id:
        raise HTTPException(status_code=422, detail="evidence_id 不能为空")
    store, project_id = _research_store(request)
    try:
        return await asyncio.to_thread(store.link_evidence, project_id=project_id, claim_id=claim_id, evidence_id=evidence_id, relation=str(body.get("relation") or "supports"), strength=body.get("strength"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/research/decisions")
async def list_research_decisions(request: Request, limit: int = 200):
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.list_decisions, project_id, limit=limit)


@router.post("/research/decisions")
async def create_research_decision(request: Request):
    body = await request.json()
    if not isinstance(body, dict) or not str(body.get("title") or "").strip():
        raise HTTPException(status_code=422, detail="title 不能为空")
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.create_decision, project_id=project_id, title=str(body["title"]), rationale=str(body.get("rationale") or ""), status=str(body.get("status") or "active"), metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else {})


@router.get("/research/runs")
async def list_research_runs(request: Request, limit: int = 100):
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.list_research_runs, project_id, limit=limit)


@router.get("/analysis/runs")
async def list_analysis_runs(request: Request, limit: int = 100):
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.list_analysis_runs, project_id, limit=limit)


@router.get("/analysis/environment")
async def analysis_environment(request: Request):
    """Return the project runtime/dependency lock used by reproducible runs."""
    return {"environment": await asyncio.to_thread(runtime_environment, _project_root(request))}


@router.get("/analysis/runs/compare")
async def compare_analysis_runs(request: Request, left_id: str, right_id: str):
    store, project_id = _research_store(request)
    runs = await asyncio.to_thread(store.list_analysis_runs, project_id, limit=1000)
    left = next((item for item in runs if str(item.get("id")) == left_id), None)
    right = next((item for item in runs if str(item.get("id")) == right_id), None)
    if left is None or right is None:
        raise HTTPException(status_code=404, detail="分析运行不存在")
    def changes(a: dict, b: dict) -> dict[str, Any]:
        keys = ("script_sha256", "inputs", "parameters", "environment", "outputs", "status", "exit_code")
        return {key: {"left": a.get(key), "right": b.get(key)} for key in keys if a.get(key) != b.get(key)}
    return {"left": left, "right": right, "changes": changes(left, right)}


@router.post("/analysis/runs")
async def create_analysis_run(request: Request):
    body = await request.json()
    store, project_id = _research_store(request)
    inputs = dict(body.get("inputs") if isinstance(body.get("inputs"), dict) else {})
    input_files = body.get("input_files") if isinstance(body, dict) and isinstance(body.get("input_files"), list) else []
    if input_files:
        snapshot = await asyncio.to_thread(snapshot_input_files, _project_root(request), [str(item) for item in input_files[:200]])
        inputs["__input_files__"] = snapshot["files"]
        inputs["__schemas__"] = snapshot["schemas"]
    environment = dict(body.get("environment") if isinstance(body.get("environment"), dict) else {})
    environment.setdefault("__runtime__", runtime_environment(_project_root(request)))
    return await asyncio.to_thread(store.create_analysis_run, project_id=project_id, script_path=body.get("script_path"), inputs=inputs, parameters=body.get("parameters") if isinstance(body.get("parameters"), dict) else {}, environment=environment, research_run_id=body.get("research_run_id"), task_id=body.get("task_id"))


@router.patch("/analysis/runs/{run_id}")
async def finish_analysis_run(run_id: str, request: Request):
    body = await request.json()
    store, project_id = _research_store(request)
    runs = await asyncio.to_thread(store.list_analysis_runs, project_id, limit=1000)
    if not any(item.get("id") == run_id for item in runs):
        raise HTTPException(status_code=404, detail="分析运行不存在")
    try:
        return await asyncio.to_thread(store.finish_analysis_run, run_id, status=str(body.get("status") or "complete"), outputs=body.get("outputs") if isinstance(body.get("outputs"), dict) else {}, stdout=str(body.get("stdout") or ""), stderr=str(body.get("stderr") or ""), exit_code=body.get("exit_code"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/analysis/runs/{run_id}/evidence")
async def attach_analysis_run_evidence(run_id: str, request: Request):
    body = await request.json()
    claim_id = str((body or {}).get("claim_id") or "").strip()
    if not claim_id:
        raise HTTPException(status_code=422, detail="claim_id 不能为空")
    store, project_id = _research_store(request)
    runs = await asyncio.to_thread(store.list_analysis_runs, project_id, limit=1000)
    run = next((item for item in runs if str(item.get("id")) == run_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail="分析运行不存在")
    try:
        evidence = await asyncio.to_thread(
            store.create_evidence, project_id=project_id, kind="analysis_run",
            source_anchor=f"analysis_run:{run_id}", excerpt=str(body.get("excerpt") or "分析运行输出"),
            artifact_path=(run.get("outputs") or {}).get("artifact_path") if isinstance(run.get("outputs"), dict) else None,
            metadata={"analysis_run_id": run_id, "script_sha256": run.get("script_sha256"), "outputs": run.get("outputs") or {}},
        )
        link = await asyncio.to_thread(store.link_evidence, project_id=project_id, claim_id=claim_id, evidence_id=evidence["id"], relation=str(body.get("relation") or "supports"), strength=body.get("strength"))
        await asyncio.to_thread(store.add_provenance_edge, project_id=project_id, from_type="analysis_run", from_id=run_id, to_type="evidence", to_id=evidence["id"], relation="produced")
        return {"evidence": evidence, "link": link}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _is_frozen() -> bool:
    """PyInstaller 冻结态判定（独立小函数，便于测试打桩）。"""
    return bool(getattr(sys, "frozen", False))


class _ScriptResult(NamedTuple):
    """跨冻结/开发两种执行路径的统一脚本执行结果。"""

    returncode: int
    stdout: str
    stderr: str


def _frozen_reproduce_bootstrap(script: Path, env_updates: dict[str, str], marker: Path) -> str:
    """生成冻结态引导代码：注入运行环境变量 → runpy 就地执行 → 回传退出码。

    frozen_exec 执行器只回传合并后的输出文本，拿不到退出码；这里用标记文件把
    SystemExit 的整型退出码带回父进程，语义对齐开发态 CompletedProcess。
    """
    lines = ["import os, runpy, sys", f"_ra_marker = {str(marker)!r}"]
    for key, value in env_updates.items():
        lines.append(f"os.environ[{key!r}] = {value!r}")
    lines += [
        f"sys.argv = [{str(script)!r}]",
        "_ra_code = 0",
        "try:",
        f"    runpy.run_path({str(script)!r}, run_name='__main__')",
        "except SystemExit as _exc:",
        "    _ra_code = _exc.code if isinstance(_exc.code, int) else (0 if _exc.code is None else 1)",
        "except BaseException:",
        "    import traceback",
        "    traceback.print_exc()",
        "    _ra_code = 1",
        "try:",
        "    from pathlib import Path as _Path",
        "    _Path(_ra_marker).write_text(str(_ra_code), encoding='ascii')",
        "except OSError:",
        "    pass",
    ]
    return "\n".join(lines)


async def _run_reproduce_script_frozen(*, script: Path, cwd: Path,
                                       env: dict[str, str], timeout: int) -> _ScriptResult:
    """冻结态薄适配：经 tools.frozen_exec 的 spawn 子进程执行器跑分析脚本。

    冻结版 sys.executable 是应用自身 exe，subprocess 它等于二次启动整个桌面
    应用并弹原生错误框——必须改走进程内执行器（与 tools.python_exec 同一套
    分流模式）。执行器只提供合并输出流，stdout/stderr 统一并入 stdout 返回；
    cwd 即脚本工作目录（同时注入为子进程内 WS 常量）。
    """
    from ..tools.frozen_exec import run_python_inprocess

    marker = Path(cwd) / f"_ra_repro_exit_{uuid.uuid4().hex[:8]}.txt"
    output = await run_python_inprocess(
        _frozen_reproduce_bootstrap(script, env, marker),
        timeout=timeout, cwd=str(cwd), workspace_root=str(cwd),
    )
    exit_code = -1  # 标记未落盘：引导代码被杀（如超时），按失败口径
    try:
        exit_code = int(marker.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        pass  # 合理降级：标记未落盘即维持上方 -1 失败口径
    try:
        marker.unlink(missing_ok=True)
    except OSError:
        pass  # 尽力而为：标记清理失败不影响脚本结果返回
    return _ScriptResult(exit_code, output, "")


async def _run_reproduce_script(*, script: Path, cwd: Path,
                                env: dict[str, str], timeout: int) -> _ScriptResult:
    """复现脚本统一执行入口：开发态子进程 / 冻结态 frozen_exec 适配层。"""
    if _is_frozen():
        return await _run_reproduce_script_frozen(script=script, cwd=cwd, env=env, timeout=timeout)
    completed = await asyncio.to_thread(
        subprocess.run, [sys.executable, str(script)], cwd=str(cwd), env=env,
        capture_output=True, text=True, timeout=timeout, check=False,
        # CREATE_NO_WINDOW：Windows 下防子进程弹终端窗口（其它平台为 0）
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return _ScriptResult(completed.returncode, completed.stdout or "", completed.stderr or "")


async def _reproduce_analysis(*, store, run_id: str, project_id: str, script: Path, root: Path,
                              inputs: dict, parameters: dict, environment: dict) -> None:
    """Run a recorded script off the request path using a stable env contract."""
    output_dir = root / "writing_outputs" / "analysis-runs" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "RA_ANALYSIS_RUN_ID": run_id,
        "RA_ANALYSIS_OUTPUT_DIR": str(output_dir),
        "RA_ANALYSIS_INPUTS_JSON": json.dumps(inputs, ensure_ascii=False),
        "RA_ANALYSIS_PARAMETERS_JSON": json.dumps(parameters, ensure_ascii=False),
    })
    try:
        completed = await _run_reproduce_script(script=script, cwd=root, env=env, timeout=3600)
        input_files = inputs.get("__input_files__") if isinstance(inputs.get("__input_files__"), list) else []
        current_snapshot = await asyncio.to_thread(snapshot_input_files, root, [str(item.get("path")) for item in input_files if isinstance(item, dict)])
        previous_schemas = inputs.get("__schemas__") if isinstance(inputs.get("__schemas__"), dict) else {}
        current_schemas = current_snapshot.get("schemas") if isinstance(current_snapshot.get("schemas"), dict) else {}
        changes = schema_changes(previous_schemas, current_schemas)
        previous_files = {str(item.get("path")): item.get("sha256") for item in input_files if isinstance(item, dict)}
        current_files = {str(item.get("path")): item.get("sha256") for item in current_snapshot.get("files", []) if isinstance(item, dict)}
        file_changes = [{"path": path, "before": previous_files.get(path), "after": current_files.get(path)} for path in sorted(set(previous_files) | set(current_files)) if previous_files.get(path) != current_files.get(path)]
        recorded_runtime = environment.get("__runtime__") if isinstance(environment.get("__runtime__"), dict) else {}
        current_runtime = runtime_environment(root)
        environment_changes = schema_changes(recorded_runtime, current_runtime)
        outputs = {"artifact_dir": str(output_dir.relative_to(root)).replace("\\", "/"), "input_schema_changes": changes, "input_file_changes": file_changes, "environment_changes": environment_changes}

        # A+ 阶段 2 / F-3：把复现产物纳入版本历史。
        #
        # 复现脚本经 subprocess 在请求循环之外写文件，**完全绕开 ToolRegistry**
        # ——产物此前只出现在 outputs_json 里，出错后无法 diff 也无法恢复。
        # 这里走显式 opt-in 的 record_tree（不采用 atomic_write_text 全局钩子：
        # 版本存储自身用它写 index.json，会造成「写索引→记变更→又写索引」的
        # 递归）。缺口如实上报，不留静默。
        try:
            from ..artifacts.versioning import ArtifactVersionStore

            scan = await asyncio.to_thread(
                ArtifactVersionStore(root).record_tree,
                output_dir, tool=f"analysis:{run_id}",
            )
            if scan.get("skipped_oversized") or scan.get("truncated"):
                LOG.warning(
                    "复现产物版本登记存在缺口 run=%s %s", run_id[:8], scan,
                )
            outputs["versioned_artifacts"] = scan
        except Exception:  # noqa: BLE001 —— 版本登记失败不能影响复现结果本身
            LOG.warning("复现产物版本登记失败 run=%s", run_id[:8], exc_info=True)

        await asyncio.to_thread(
            store.finish_analysis_run, run_id,
            status="complete" if completed.returncode == 0 else "failed", outputs=outputs,
            stdout=completed.stdout or "", stderr=completed.stderr or "", exit_code=completed.returncode,
        )
        if completed.returncode != 0:
            await asyncio.to_thread(
                store.create_quality_item, project_id=project_id, object_type="analysis_run",
                object_id=run_id, gate="reproducibility", severity="error",
                message="复现脚本退出码非零", details={"exit_code": completed.returncode},
            )
        if changes or file_changes or environment_changes:
            await asyncio.to_thread(
                store.create_quality_item, project_id=project_id, object_type="analysis_run",
                object_id=run_id, gate="input_schema", severity="warning",
                message="复现时输入、schema 或运行环境已变化", details={"schema_changes": changes, "file_changes": file_changes, "environment_changes": environment_changes},
            )
        await asyncio.to_thread(
            store.create_notification, project_id=project_id,
            kind="analysis_complete" if completed.returncode == 0 else "analysis_failed",
            title="分析复现已完成" if completed.returncode == 0 else "分析复现失败",
            message=f"运行 {run_id[:8]} · exit={completed.returncode}",
            object_type="analysis_run", object_id=run_id,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        await asyncio.to_thread(
            store.finish_analysis_run, run_id, status="failed", outputs={},
            stderr=str(exc), exit_code=-1,
        )
        await asyncio.to_thread(
            store.create_quality_item, project_id=project_id, object_type="analysis_run",
            object_id=run_id, gate="reproducibility", severity="error", message=f"复现执行失败：{exc}",
        )


@router.post("/analysis/runs/{run_id}/rerun")
async def rerun_analysis_run(run_id: str, request: Request):
    store, project_id = _research_store(request)
    runs = await asyncio.to_thread(store.list_analysis_runs, project_id, limit=1000)
    original = next((item for item in runs if str(item.get("id")) == run_id), None)
    if original is None:
        raise HTTPException(status_code=404, detail="分析运行不存在")
    script_raw = str(original.get("script_path") or "")
    if not script_raw:
        raise HTTPException(status_code=422, detail="该运行没有可复现脚本")
    root = _project_root(request)
    try:
        script = safe_resolve(Path(script_raw), root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="脚本路径越界，拒绝执行") from exc
    if not script.is_file() or script.suffix.lower() != ".py":
        raise HTTPException(status_code=422, detail="复现脚本不存在或不是 Python 文件")
    fresh = await asyncio.to_thread(
        store.create_analysis_run, project_id=project_id, script_path=str(script),
        inputs=original.get("inputs") if isinstance(original.get("inputs"), dict) else {},
        parameters=original.get("parameters") if isinstance(original.get("parameters"), dict) else {},
        environment=original.get("environment") if isinstance(original.get("environment"), dict) else {},
    )
    await asyncio.to_thread(
        store.add_provenance_edge, project_id=project_id, from_type="analysis_run", from_id=run_id,
        to_type="analysis_run", to_id=fresh["id"], relation="reproduced_from",
    )
    task = asyncio.create_task(_reproduce_analysis(
        store=store, run_id=fresh["id"], project_id=project_id, script=script, root=root,
        inputs=fresh.get("inputs") or {}, parameters=fresh.get("parameters") or {}, environment=fresh.get("environment") or {},
    ))
    request.app.state.analysis_tasks = getattr(request.app.state, "analysis_tasks", set())
    request.app.state.analysis_tasks.add(task)
    task.add_done_callback(request.app.state.analysis_tasks.discard)
    return {"run": fresh, "source_run_id": run_id, "status": "queued"}


@router.post("/research/runs")
async def create_research_run(request: Request):
    body = await request.json()
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.create_research_run, project_id=project_id, task_id=body.get("task_id"), workflow_id=body.get("workflow_id"), inputs=body.get("inputs") if isinstance(body.get("inputs"), dict) else {}, environment=body.get("environment") if isinstance(body.get("environment"), dict) else {})


@router.patch("/research/runs/{run_id}")
async def finish_research_run(run_id: str, request: Request):
    body = await request.json()
    status = str((body or {}).get("status") or "complete")
    if status not in {"complete", "failed", "cancelled", "interrupted"}:
        raise HTTPException(status_code=422, detail="无效的运行状态")
    store, project_id = _research_store(request)
    runs = await asyncio.to_thread(store.list_research_runs, project_id, limit=1000)
    if not any(str(item.get("id")) == run_id for item in runs):
        raise HTTPException(status_code=404, detail="运行不存在")
    return await asyncio.to_thread(store.finish_research_run, run_id, status=status, outputs=body.get("outputs") if isinstance(body.get("outputs"), dict) else {})


@router.get("/research/provenance")
async def list_research_provenance(request: Request, object_type: str | None = None, object_id: str | None = None, limit: int = 500):
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.list_provenance, project_id, object_type=object_type, object_id=object_id, limit=limit)


@router.get("/scheduler/jobs")
async def list_scheduler_jobs(request: Request, status: str | None = None, limit: int = 100):
    store, project_id = _research_store(request)
    await asyncio.to_thread(store.recover_expired_jobs)
    return await asyncio.to_thread(store.list_jobs, project_id, status=status, limit=limit)


@router.get("/scheduler/workflows")
async def list_scheduler_workflows(request: Request, workflow_id: str | None = None, limit: int = 200):
    store, project_id = _research_store(request)
    persisted = await asyncio.to_thread(store.list_workflow_definitions, project_id, workflow_id=workflow_id, limit=limit)
    if persisted:
        return persisted
    # Expose built-ins even before a project customizes them.
    return get_workflow_registry().list_workflows()


@router.post("/scheduler/workflows")
async def save_scheduler_workflow(request: Request):
    body = await request.json()
    workflow_id = str((body or {}).get("id") or "").strip()
    definition = body.get("definition") if isinstance(body, dict) else None
    if not workflow_id or not isinstance(definition, dict):
        raise HTTPException(status_code=422, detail="工作流 id/definition 不完整")
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.save_workflow_definition, project_id=project_id, workflow_id=workflow_id, definition=definition, enabled=bool(body.get("enabled", True)), version=body.get("version"))


@router.get("/scheduler/triggers")
async def list_scheduler_triggers(request: Request, limit: int = 100):
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.list_workflow_triggers, project_id, limit=limit)


@router.post("/scheduler/triggers")
async def create_scheduler_trigger(request: Request):
    body = await request.json()
    workflow_id = str((body or {}).get("workflow_id") or "").strip()
    if not workflow_id:
        raise HTTPException(status_code=422, detail="workflow_id 不能为空")
    store, project_id = _research_store(request)
    try:
        return await asyncio.to_thread(store.create_workflow_trigger, project_id=project_id, workflow_id=workflow_id, interval_seconds=float(body.get("interval_seconds") or 0), payload=_safe_scheduler_payload(body.get("payload")), next_run=body.get("next_run"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/scheduler/triggers/{trigger_id}")
async def set_scheduler_trigger_enabled(trigger_id: str, request: Request):
    """R17：触发器启停（此前 enabled 只读、UI 无开关）。"""
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict) or body.get("enabled") is None:
        raise HTTPException(status_code=422, detail="需要 enabled 字段")
    store, project_id = _research_store(request)
    item = await asyncio.to_thread(
        store.set_workflow_trigger_enabled, trigger_id, project_id,
        enabled=bool(body.get("enabled")),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="触发器不存在")
    return item


@router.delete("/scheduler/triggers/{trigger_id}")
async def delete_scheduler_trigger(trigger_id: str, request: Request):
    """R17：删除触发器（此前 UI 无删除入口）。"""
    store, project_id = _research_store(request)
    ok = await asyncio.to_thread(store.delete_workflow_trigger, trigger_id, project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="触发器不存在")
    return {"ok": True}


@router.get("/runs/search")
async def search_runs(
    request: Request,
    q: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """R17：历史运行检索（标题子串 + 状态过滤 + 分页）。

    替换前端运行历史 slice(0,20) 硬截断——total 随响应返回，
    前端据此渲染分页器。
    """
    store = request.app.state.platform_store
    project_id = (getattr(request.app.state, "project", None) or {}).get("id")
    return await asyncio.to_thread(
        store.search_runs, project_id, query=q, status=status,
        limit=limit, offset=offset,
    )


@router.get("/settings/{key}")
async def get_ui_setting(key: str, request: Request):
    """R17：跨端 UI 设置读取（如 verbosity）。"""
    store = getattr(request.app.state, "platform_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="平台存储不可用")
    value = await asyncio.to_thread(store.get_setting, key)
    return {"key": key, "value": value}


@router.put("/settings/{key}")
async def put_ui_setting(key: str, request: Request):
    """R17：跨端 UI 设置写入（替代纯 localStorage，换浏览器不丢）。"""
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict) or body.get("value") is None:
        raise HTTPException(status_code=422, detail="需要 value 字段")
    store = getattr(request.app.state, "platform_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="平台存储不可用")
    await asyncio.to_thread(store.set_setting, key, str(body["value"]))
    return {"ok": True, "key": key, "value": str(body["value"])}


@router.get("/search")
async def unified_search(request: Request, q: str = "", scope: str = "all", limit: int = 20):
    """R17：统一检索入口（Ctrl+K 与历史页共用）。

    scope: ``tasks``（标题，走 search_runs）| ``sessions``（会话目录标题）
    | ``artifacts``（产物文件名/路径，读 artifacts 索引——由会话 manifest
    端点回填，迭代2）| ``all``。
    """
    q = q.strip()
    if not q:
        return {"sessions": [], "tasks": [], "artifacts": []}
    result: dict[str, Any] = {"sessions": [], "tasks": [], "artifacts": []}
    cwd = getattr(request.app.state, "cwd", None) or Path.cwd()
    if scope in {"all", "sessions"}:
        sessions_root = cwd / ".ra" / "sessions"
        hits: list[dict[str, Any]] = []
        if sessions_root.is_dir():
            needle = q.lower()
            for child in sorted(sessions_root.iterdir()):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                state_file = child / "run.json"
                try:
                    state = json.loads(state_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                title = str(state.get("query") or "")
                if needle in title.lower() or needle in child.name.lower():
                    hits.append({
                        "id": child.name, "title": title or None,
                        "updated_at": state.get("updated_at"),
                    })
                if len(hits) >= limit:
                    break
        result["sessions"] = hits
    if scope in {"all", "tasks"}:
        store = getattr(request.app.state, "platform_store", None)
        project_id = (getattr(request.app.state, "project", None) or {}).get("id")
        if store is not None:
            found = await asyncio.to_thread(
                store.search_runs, project_id, query=q, limit=limit,
            )
            result["tasks"] = found["items"]
    if scope in {"all", "artifacts"}:
        store = getattr(request.app.state, "platform_store", None)
        if store is not None:
            result["artifacts"] = await asyncio.to_thread(
                store.search_artifacts, q, limit,
            )
    return result


@router.post("/scheduler/jobs")
async def enqueue_scheduler_job(request: Request):
    body = await request.json()
    workflow_id = str((body or {}).get("workflow_id") or "").strip()
    if not workflow_id:
        raise HTTPException(status_code=422, detail="workflow_id 不能为空")
    store, project_id = _research_store(request)
    # Built-ins and validated project definitions are both schedulable.  The
    # dispatcher performs the same role/dependency validation before running.
    if workflow_id != "single":
        try:
            get_workflow_registry().get_workflow(workflow_id)
        except KeyError:
            persisted = await asyncio.to_thread(
                store.list_workflow_definitions, project_id, workflow_id=workflow_id, limit=1,
            )
            if not persisted:
                raise HTTPException(status_code=422, detail=f"未知工作流: {workflow_id}") from None
    return await asyncio.to_thread(store.enqueue_job, project_id=project_id, workflow_id=workflow_id, payload=_safe_scheduler_payload(body.get("payload")), max_attempts=body.get("max_attempts") or 3, run_after=body.get("run_after"), priority=body.get("priority") or 0, estimated_seconds=body.get("estimated_seconds"), resource_key=str(body.get("resource_key") or ""))


@router.post("/scheduler/jobs/{job_id}/retry")
async def retry_scheduler_job(job_id: str, request: Request):
    store, project_id = _research_store(request)
    jobs = await asyncio.to_thread(store.list_jobs, project_id, limit=1000)
    job = next((item for item in jobs if item.get("id") == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail="队列任务不存在")
    # Resetting a terminal job creates an auditable new attempt while keeping
    # the original row's history in ``last_error``.
    return await asyncio.to_thread(store.enqueue_job, project_id=project_id, workflow_id=str(job["workflow_id"]), payload=_safe_scheduler_payload(job.get("payload")), max_attempts=int(job.get("max_attempts") or 3))


@router.post("/research/provenance")
async def add_research_provenance(request: Request):
    body = await request.json()
    required = ("from_type", "from_id", "to_type", "to_id", "relation")
    if not isinstance(body, dict) or any(not str(body.get(key) or "").strip() for key in required):
        raise HTTPException(status_code=422, detail="provenance 边字段不完整")
    store, project_id = _research_store(request)
    return await asyncio.to_thread(store.add_provenance_edge, project_id=project_id, from_type=str(body["from_type"]), from_id=str(body["from_id"]), to_type=str(body["to_type"]), to_id=str(body["to_id"]), relation=str(body["relation"]), metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else {})


@router.get("/tasks/{task_id}/events")
async def get_platform_task_events(
    task_id: str, request: Request, after: int = 0, limit: int = 2000,
):
    store = request.app.state.platform_store
    task = await asyncio.to_thread(store.get_task, task_id)
    if task is None or task["project_id"] != request.app.state.project["id"]:
        raise HTTPException(status_code=404, detail="任务不存在")
    events = await asyncio.to_thread(store.read_events, task_id, after=after, limit=limit)
    return {"events": events, "last_seq": events[-1]["seq"] if events else after}


@router.get("/papers")
async def list_papers(request: Request):
    output_folder = request.app.state.output_folder

    def _collect() -> list[dict]:
        papers = find_existing_papers(output_folder)
        return [_paper_summary(p["path"]) for p in papers]

    # 每个 paper 目录都要同步解析 docx 数词/标题，属重 IO——放线程池，
    # 避免论文多时卡死事件循环（全部 WS 流一起断）。
    return await asyncio.to_thread(_collect)


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


def _parse_events_file(events_file: Path) -> list[dict]:
    """整份读入并逐行解析 events.jsonl，坏行跳过（同步函数，端点经线程池调用）。

    TODO(B2+): 大文件应记录字节偏移做增量读取，避免每次整份载入内存。
    """
    parsed: list[dict] = []
    if not events_file.is_file():  # 文件不存在时返回空集而非报错
        return parsed
    text = events_file.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # 跳过坏行
        if isinstance(event, dict):
            parsed.append(event)
    return parsed


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
    # 整份 read_text + 逐行 parse 是同步重 IO，放线程池避免卡事件循环
    parsed: list[dict] = await asyncio.to_thread(_parse_events_file, events_file)

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
            # 真实错误上报：文件登记在案却读不出，静默返回空内容会误导前端
            LOG.warning("summary 文件读取失败: %s", info["summary"], exc_info=True)

    progress_content = ""
    if info.get("progress_log"):
        try:
            progress_content = Path(info["progress_log"]).read_text(encoding="utf-8")
        except Exception:
            LOG.warning("progress_log 文件读取失败: %s", info["progress_log"], exc_info=True)

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

    # image/svg+xml 可内嵌 <script>，属 XSS 载体，绝不允许 inline 渲染——
    # 一律走 attachment 下载（浏览器直接打开才会执行其中的脚本）。
    inline_types = {"application/pdf", "image/png", "image/jpeg", "image/gif"}
    disposition = "inline" if mime in inline_types else "attachment"

    return FileResponse(
        path=str(full_path),
        media_type=mime,
        headers={"Content-Disposition": f'{disposition}; filename="{full_path.name}"'},
    )


def _build_paper_export_bytes(paper_dir: Path) -> bytes:
    """内存打包整个论文目录（同步重 IO，由端点经线程池调用）。

    Internal ``.ra`` state and ``__pycache__`` directories are excluded.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(paper_dir.rglob("*")):
            rel = path.relative_to(paper_dir)
            if any(part in _EXPORT_SKIP_DIRS for part in rel.parts):
                continue
            if path.is_file():
                zf.write(path, arcname=rel.as_posix())
    return buf.getvalue()


@router.get("/papers/{paper_name}/export")
async def export_paper(paper_name: str, request: Request):
    """Zip the entire paper directory for download (B6)."""
    output_folder = Path(request.app.state.output_folder)
    if not output_folder.is_dir():
        raise HTTPException(status_code=404, detail="输出目录不存在")
    try:
        paper_dir = _safe_run_dir(output_folder, paper_name)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="路径不合法") from exc
    if not paper_dir.is_dir():
        raise HTTPException(status_code=404, detail="文档不存在")

    # rglob + zip 压缩是同步重 IO，放线程池避免卡死事件循环
    payload = await asyncio.to_thread(_build_paper_export_bytes, paper_dir)
    zip_name = f"{paper_dir.name}.zip"
    return Response(
        content=payload,
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

    # 递归删除可能很慢（大量产物文件），放线程池避免卡死事件循环
    await asyncio.to_thread(shutil.rmtree, paper_dir)
    return {"ok": True}


def _rel(path: str | None, base: Path) -> str | None:
    """Convert absolute path to relative path string, using forward slashes."""
    if not path:
        return None
    try:
        return str(Path(path).relative_to(base)).replace("\\", "/")
    except ValueError:
        return None
