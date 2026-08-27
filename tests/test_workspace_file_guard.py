"""GET /api/workspace/file 安全护栏回归测试（缺陷 F）。

- 敏感目标拒绝：相对路径任一段命中 ``.env*`` / ``.ra*`` / ``.git*`` → 403，
  且先于存在性判断（避免用 404/200 探测密钥文件是否存在）；
- SVG 强制 attachment：SVG 可内嵌脚本，浏览器同源渲染有 XSS 风险。
"""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from research_assistant.web.workspace import router as workspace_router  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """带敏感文件样本的轻量应用：只挂 workspace 路由，根指向 tmp。"""
    root = tmp_path / "ws"
    root.mkdir()
    (root / ".env").write_text("SECRET=1", encoding="utf-8")
    ra = root / ".ra"
    ra.mkdir()
    (ra / "platform.sqlite3").write_bytes(b"sqlite")
    git = root / ".git"
    git.mkdir()
    (git / "config").write_text("[core]", encoding="utf-8")
    sub = root / "sub"
    sub.mkdir()
    (sub / ".env.local").write_text("X=1", encoding="utf-8")
    docs = root / "docs"
    docs.mkdir()
    (docs / "readme.txt").write_text("readme", encoding="utf-8")
    (root / "notes.md").write_text("# hello", encoding="utf-8")
    (root / "logo.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        encoding="utf-8",
    )
    app = FastAPI()
    app.include_router(workspace_router, prefix="/api")
    app.state.cwd = root.resolve()
    yield TestClient(app)


def _get(client: TestClient, path: str):
    return client.get("/api/workspace/file", params={"path": path})


class TestProtectedTargets:
    def test_dotenv_rejected(self, client):
        assert _get(client, ".env").status_code == 403

    def test_nested_dotenv_rejected(self, client):
        assert _get(client, "sub/.env.local").status_code == 403

    def test_internal_state_dir_rejected(self, client):
        assert _get(client, ".ra/platform.sqlite3").status_code == 403

    def test_git_dir_rejected(self, client):
        assert _get(client, ".git/config").status_code == 403

    def test_protected_check_precedes_existence(self, tmp_path, client):
        # 不存在的敏感路径同样 403：不能借 404 探测密钥文件是否存在
        assert _get(client, ".env.production").status_code == 403


class TestNormalFilesUnaffected:
    def test_markdown_preview(self, client):
        resp = _get(client, "notes.md")
        assert resp.status_code == 200
        body = resp.json()
        assert body["kind"] == "text"
        assert "# hello" in body["content"]

    def test_nested_text_file(self, client):
        resp = _get(client, "docs/readme.txt")
        assert resp.status_code == 200
        assert resp.json()["content"] == "readme"

    def test_missing_normal_file_still_404(self, client):
        assert _get(client, "docs/ghost.md").status_code == 404


class TestSvgDisposition:
    def test_svg_forced_attachment(self, client):
        resp = _get(client, "logo.svg")
        assert resp.status_code == 200
        assert resp.headers["content-disposition"].lower().startswith("attachment")
