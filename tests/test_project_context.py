"""Tests for project-level long-term instructions."""

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from research_assistant.runtime import PlatformStore  # noqa: E402
from research_assistant.web.routes import router  # noqa: E402


def _app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    app.state.platform_store = store
    app.state.project = store.ensure_project(tmp_path)
    return app


class TestProjectInstructions:
    def test_default_empty(self, tmp_path):
        client = TestClient(_app(tmp_path))
        r = client.get("/api/project/instructions")
        assert r.status_code == 200
        assert r.json()["instructions"] == ""

    def test_put_then_get(self, tmp_path):
        app = _app(tmp_path)
        client = TestClient(app)
        r = client.put(
            "/api/project/instructions",
            json={"instructions": "引用采用 Nature 格式"},
        )
        assert r.status_code == 200
        # state refreshed so subsequent reads see the new value
        assert app.state.project["instructions"] == "引用采用 Nature 格式"
        assert client.get("/api/project/instructions").json()[
            "instructions"
        ] == "引用采用 Nature 格式"

    def test_persisted_in_sqlite(self, tmp_path):
        app = _app(tmp_path)
        client = TestClient(app)
        client.put("/api/project/instructions", json={"instructions": "abc"})
        reopened = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
        project = reopened.ensure_project(tmp_path)
        assert project["instructions"] == "abc"
