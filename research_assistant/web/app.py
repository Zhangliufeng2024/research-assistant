"""FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..config import (
    app_config_env_path,
    ensure_global_config,
    load_project_env,
    resolve_model,
)
from ..core import ensure_output_folder, setup_claude_skills


@asynccontextmanager
async def lifespan(app: FastAPI):
    cwd = Path.cwd().resolve()
    ensure_global_config(cwd)  # 老工作区 .env 配置一次性上移到全局（R8）
    load_project_env(cwd)

    package_dir = Path(__file__).parent.parent.absolute()
    setup_claude_skills(package_dir, cwd)

    app.state.cwd = cwd
    app.state.output_folder = ensure_output_folder(cwd)
    # 设置页存储位置：全局配置文件（切换工作目录不丢，R8 反馈 #1 配套）。
    # 测试可覆写 app.state.env_file 指向临时目录。
    app.state.env_file = app_config_env_path()
    app.state.model = resolve_model()
    app.state.active_tasks = {}

    yield


def create_app() -> FastAPI:
    app = FastAPI(title="研究助手", lifespan=lifespan)

    from .chat import router as chat_router
    from .routes import router as api_router
    from .settings import router as settings_router
    from .workspace import router as workspace_router
    from .ws import router as ws_router

    app.include_router(api_router, prefix="/api")
    app.include_router(workspace_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    # chat 挂两次：REST 走 /api 前缀；/ws/chat 由前端硬编码，需再裸挂一次（见 protocol.md §10）
    app.include_router(chat_router, prefix="/api")
    app.include_router(chat_router)
    app.include_router(ws_router)

    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
