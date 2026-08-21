"""Tests for the web task-stop endpoint."""

import asyncio

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from research_assistant.web.routes import router  # noqa: E402


def _app_with_task(task_id: str, with_event: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.model = "m"
    app.state.output_folder = None
    app.state.active_tasks = {}
    if with_event:
        app.state.active_tasks[task_id] = {
            "status": "running",
            "query": "q",
            "cancel_event": asyncio.Event(),
        }
    else:
        app.state.active_tasks[task_id] = {"status": "running", "query": "q"}
    return app


class TestStopEndpoint:
    def test_stop_sets_cancel_event(self):
        app = _app_with_task("t1")
        client = TestClient(app)
        resp = client.post("/api/tasks/t1/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopping"
        assert app.state.active_tasks["t1"]["cancel_event"].is_set()

    def test_stop_unknown_task_404(self):
        client = TestClient(_app_with_task("t1"))
        resp = client.post("/api/tasks/ghost/stop")
        assert resp.status_code == 404

    def test_stop_task_without_event_409(self):
        client = TestClient(_app_with_task("legacy", with_event=False))
        resp = client.post("/api/tasks/legacy/stop")
        assert resp.status_code == 409
