"""Real browser acceptance flow for the unified research workspace.

Run from the repository root after ``cd frontend; npm run build``:
``python scripts/e2e_research_os.py``.
It starts an isolated FastAPI project, drives the compiled UI with Edge, and
uses only project-scoped REST calls to seed deterministic non-LLM fixtures.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from research_assistant.runtime import PlatformStore

REPO = Path(__file__).resolve().parents[1]
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def wait_for_server(page, url: str) -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if page.request.get(f"{url}/api/status", timeout=2000).ok:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("server did not become ready")


def main() -> None:
    if not EDGE.is_file():
        raise RuntimeError(f"Edge executable not found: {EDGE}")
    root = Path(tempfile.mkdtemp(prefix="ra-browser-e2e-"))
    server = None
    try:
        (root / "writing_outputs").mkdir(parents=True)
        artifact = root / "writing_outputs" / "draft.md"
        artifact.write_text("# Browser-reviewed draft\n", encoding="utf-8")
        script = root / "analysis.py"
        script.write_text("from pathlib import Path\nPath('analysis-result.txt').write_text('ok', encoding='utf-8')\nprint('reproduced')\n", encoding="utf-8")
        data = root / "input.csv"
        data.write_text("method,score\nA,0.9\n", encoding="utf-8")
        source = root / "source.md"
        source.write_text("# Imported source\nEvidence anchor for the browser flow.", encoding="utf-8")
        store = PlatformStore(root / ".ra" / "platform.sqlite3")
        project = store.ensure_project(root, "Browser Research OS")
        store.review_artifact(
            project_id=project["id"], artifact_path="writing_outputs/draft.md", status="pending",
            metadata={"sha256": store.file_sha256(artifact), "size": artifact.stat().st_size, "artifact_type": "md", "quality_gate_status": "passed"},
        )
        env = os.environ.copy()
        env.update({"PYTHONPATH": str(REPO), "RA_RESEARCH_OS": "1", "RA_SCHEDULER_CONCURRENCY": "1", "RA_PROVIDER_CONCURRENCY": "1"})
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "research_assistant.web.app:create_app", "--factory", "--host", "127.0.0.1", "--port", "18765", "--log-level", "error"],
            cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        base = "http://127.0.0.1:18765"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE), args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            wait_for_server(page, base)

            # Live polling/WebSocket traffic means networkidle never settles.
            page.goto(f"{base}/#/", wait_until="domcontentloaded")
            expect(page.get_by_role("heading", name="Browser Research OS", exact=True)).to_be_visible()
            expect(page.get_by_text("研究工作台", exact=True)).to_be_visible()

            page.goto(f"{base}/#/research", wait_until="domcontentloaded")
            page.get_by_placeholder("例如：数据稀疏时方法是否仍稳健？").fill("浏览器验收研究问题")
            page.get_by_role("button", name="问题", exact=True).click()
            expect(page.get_by_text("浏览器验收研究问题", exact=True)).to_be_visible()
            page.get_by_placeholder("例如：方法 A 在三个数据集上优于基线").fill("浏览器验收主张")
            page.get_by_role("button", name="记录", exact=True).click()
            expect(page.get_by_text("浏览器验收主张", exact=True)).to_be_visible()

            page.goto(f"{base}/#/sources", wait_until="domcontentloaded")
            page.locator('input[type="file"]').set_input_files(str(source))
            page.wait_for_timeout(1000)
            expect(page.get_by_text("已导入 1 份资料", exact=False)).to_be_visible(timeout=10000)
            expect(page.get_by_text("source.md", exact=True)).to_be_visible()

            analysis = page.request.post(f"{base}/api/analysis/runs", data={"script_path": str(script), "input_files": ["input.csv"], "parameters": {"seed": 7}})
            assert analysis.ok, analysis.text()
            page.goto(f"{base}/#/analysis", wait_until="domcontentloaded")
            expect(page.get_by_text("analysis.py", exact=False).first).to_be_visible()
            page.get_by_role("button", name="复现运行", exact=True).click()
            expect(page.get_by_text("已创建复现运行", exact=False)).to_be_visible()

            page.goto(f"{base}/#/artifacts", wait_until="domcontentloaded")
            expect(page.get_by_text("writing_outputs/draft.md", exact=True).first).to_be_visible()
            expect(page.get_by_text("# Browser-reviewed draft", exact=False)).to_be_visible()
            page.get_by_role("button", name="要求 Agent 修改", exact=True).click()
            expect(page.get_by_text("writing_outputs/draft.md", exact=True).first).to_be_visible()

            page.goto(f"{base}/#/", wait_until="domcontentloaded")
            with page.expect_download(timeout=10000) as download_info:
                page.get_by_role("link", name="导出研究包", exact=True).click()
            download = download_info.value
            assert download.suggested_filename.endswith(".research.zip")
            print("[UI-E2E-RESEARCH-OS] PASS")
            browser.close()
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
