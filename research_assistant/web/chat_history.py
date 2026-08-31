"""会话历史治理 REST（工程债拆分，2026-08-31）。

从 ``web/chat.py`` 抽出：截断 / 编辑用户消息 / 附件上传三个端点及其目录
解析守卫。会话运行时（ws_chat）与其余 REST CRUD 仍在 chat.py，本 router
由 chat.py 的 router ``include_router`` 合并挂载。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from .chat_protocol import MAX_USER_LENGTH, UPLOAD_TOTAL_LIMIT, _safe_upload_name
from .chat_state import (
    _ACTIVE,
    _TOMBSTONES,
    _cwd_of,
    _outputs_root,
    _read_history,
    _resolve_session_dir,
    _write_history,
)

router = APIRouter()


def _history_write_conflict(session_id: str) -> HTTPException | None:
    """历史改写类端点共用的运行中守卫：回合在跑时历史正被追加，不可截断。"""
    if session_id in _ACTIVE:
        return HTTPException(status_code=409, detail="回合运行中，请等待结束后再操作历史")
    return None


def _resolve_session_or_404(session_id: str, request: Request) -> Path:
    """REST 历史治理端点共用的目录解析：403/404/墓碑 404 口径一致。"""
    try:
        run_dir = _resolve_session_dir(_cwd_of(request), session_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="会话 ID 不合法") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    if session_id in _TOMBSTONES:
        raise HTTPException(status_code=404, detail="会话不存在")
    return run_dir


@router.post("/chat/sessions/{session_id}/truncate")
async def truncate_history(session_id: str, request: Request):
    """把 history.json 截断为前 *keep* 条（真·重新生成 / 编辑重发的支点）。

    前端「重新生成」= 截断到目标用户消息之后 + 原文重发；「编辑重发」=
    先 PATCH 该消息文本、再截断、再重发——三步全部服务端落盘，重开 会话
    时被历史回灌的不再是旧答案。409 保护运行中的回合。
    """
    conflict = _history_write_conflict(session_id)
    if conflict is not None:
        raise conflict
    try:
        body = await request.json()
    except Exception:
        body = None
    try:
        keep = int((body or {}).get("keep"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="keep 必须是整数") from None
    if keep < 0:
        raise HTTPException(status_code=422, detail="keep 不能为负数")
    run_dir = _resolve_session_or_404(session_id, request)
    messages = _read_history(run_dir)
    kept = min(keep, len(messages))
    _write_history(run_dir, messages[:kept])
    return {"ok": True, "kept": kept, "removed": len(messages) - kept}


@router.patch("/chat/sessions/{session_id}/messages/{index}")
async def edit_user_message(session_id: str, index: int, request: Request):
    """就地改写一条 user 消息文本（编辑重发第一步）。assistant 条目不可改。"""
    conflict = _history_write_conflict(session_id)
    if conflict is not None:
        raise conflict
    try:
        body = await request.json()
    except Exception:
        body = None
    text = str((body or {}).get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="消息内容不能为空")
    if len(text) > MAX_USER_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"消息过长（最大 {MAX_USER_LENGTH} 字符）",
        )
    run_dir = _resolve_session_or_404(session_id, request)
    messages = _read_history(run_dir)
    if index < 0 or index >= len(messages):
        raise HTTPException(status_code=404, detail="消息序号不存在")
    if messages[index].get("role") != "user":
        raise HTTPException(status_code=422, detail="只能编辑用户消息")
    messages[index]["content"] = text
    _write_history(run_dir, messages)
    return {"ok": True, "index": index}


@router.post("/chat/sessions/{session_id}/attachments")
async def upload_chat_attachments(session_id: str, request: Request):
    """multipart 附件上传：文件落入本会话产物目录的 uploads/ 子目录。

    双轨制口径：uploads 挂在 outputs/<sid>/（写锚点）之内，send 时引用
    校验与这里同一围栏；文件名消毒 + 总量上限，1MB 流式写盘避免整文件
    进内存。运行中的回合也允许上传（本轮用不上，下一条消息即可引用）。
    """
    run_dir = _resolve_session_or_404(session_id, request)
    del run_dir  # 仅作存在性校验；落盘位置由双轨制决定
    cwd = _cwd_of(request)
    try:
        form = await request.form()
    except Exception:
        raise HTTPException(
            status_code=422, detail="请求不是合法的 multipart 表单"
        ) from None
    files = [v for v in form.values() if hasattr(v, "read")]
    if not files:
        raise HTTPException(status_code=422, detail="至少需要一个文件字段")

    dest = _outputs_root(cwd) / session_id / "uploads"
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"无法创建附件目录：{exc}") from exc

    stamp = datetime.now().strftime("%H%M%S_%f")
    results: list[dict] = []
    total = 0
    for i, uf in enumerate(files):
        safe_name = _safe_upload_name(getattr(uf, "filename", "") or "file.bin")
        target = dest / f"{stamp}_{i}_{safe_name}"
        overflow = False
        size = 0
        try:
            with open(target, "wb") as fh:
                while True:
                    chunk = await uf.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > UPLOAD_TOTAL_LIMIT:
                        overflow = True
                        break
                    fh.write(chunk)
                    size += len(chunk)
        except OSError as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"附件写盘失败：{exc}") from exc
        if overflow:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=413, detail="上传总量超过上限（50MB）")
        results.append({"name": safe_name, "path": str(target), "size": size})
    return {"files": results}
