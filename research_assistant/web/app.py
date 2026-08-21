"""FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..config import load_project_env, resolve_model
from ..core import ensure_output_folder, setup_claude_skills


@asynccontextmanager
async def lifespan(app: FastAPI):
    cwd = Path.cwd().resolve()
    load_project_env(cwd)

    package_dir = Path(__file__).parent.parent.absolute()
    setup_claude_skills(package_dir, cwd)

    app.state.cwd = cwd
    app.state.output_folder = ensure_output_folder(cwd)
    app.state.model = resolve_model()
    app.state.active_tasks = {}

    yield


def create_app() -> FastAPI:
    app = FastAPI(title="研究助手", lifespan=lifespan)

    from .routes import router as api_router
    from .ws import router as ws_router

    app.include_router(api_router, prefix="/api")
    app.include_router(ws_router)

    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
