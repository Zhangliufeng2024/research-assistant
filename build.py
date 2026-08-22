"""Build script — creates standalone Windows .exe via PyInstaller.

R7 起默认打包为**无黑框桌面应用**（--noconsole，单窗口 pywebview 壳，
诊断走 <工作区>/.ra/logs/desktop.log）。调试时可加 --debug-console 保留控制台。

Usage:
    python build.py                    # 无控制台桌面版（发布用）
    python build.py --debug-console    # 保留控制台的调试版
    python build.py --restricted       # restricted version (3-month expiry)
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
DIST = ROOT / "dist"
BUILD = ROOT / "build"
PACKAGE = ROOT / "research_assistant"


def check_env_safety():
    env_file = ROOT / ".env"
    if env_file.exists():
        content = env_file.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key, value = key.strip(), value.strip()
            if key.endswith("_KEY") and value and value != "your-api-key-here" and len(value) > 10:
                print(f"WARNING: .env contains a real key for {key}!")
                print("The .env file will NOT be bundled into the exe.")
                print("User keys are configured via the GUI at runtime.")
                break
    print("[OK] .env safety check passed.\n")


def _get_datas():
    static_dir = PACKAGE / "web" / "static"
    claude_dir = PACKAGE / ".claude"
    root_claude_dir = ROOT / ".claude"

    if not static_dir.exists():
        print(f"ERROR: {static_dir} not found!")
        sys.exit(1)

    clean_claude_dir = BUILD / "_claude_clean"
    if clean_claude_dir.exists():
        shutil.rmtree(clean_claude_dir)

    datas = [f"{static_dir};research_assistant/web/static"]

    if claude_dir.exists():
        datas.append(f"{claude_dir};research_assistant/.claude")

    if root_claude_dir.exists():
        exclude = {"settings.local.json", "plans", "memory", "skills.zip"}
        shutil.copytree(
            root_claude_dir, clean_claude_dir,
            ignore=shutil.ignore_patterns(*exclude),
            dirs_exist_ok=True,
        )
        datas.append(f"{clean_claude_dir};.claude")

    return datas


HIDDEN_IMPORTS = [
    "uvicorn", "uvicorn.lifespan", "uvicorn.lifespan.on",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "fastapi", "starlette", "starlette.routing", "starlette.responses",
    "starlette.staticfiles", "starlette.websockets",
    "httpx", "httpx._transports", "httpx._transports.default",
    "httpcore", "httpcore._async", "httpcore._backends",
    "httpcore._backends.auto", "httpcore._backends.anyio",
    "h11", "anyio", "anyio._backends", "anyio._backends._asyncio", "sniffio",
    "dotenv", "docx", "docx.opc", "docx.opc.constants", "fitz",
    "research_assistant", "research_assistant.web",
    "research_assistant.web.app", "research_assistant.web.routes", "research_assistant.web.ws",
    "research_assistant.api", "research_assistant.agent", "research_assistant.cli",
    "research_assistant.config", "research_assistant.core", "research_assistant.constants",
    "research_assistant.models", "research_assistant.docgen", "research_assistant.orchestrator",
    "research_assistant.retry", "research_assistant.display", "research_assistant.steer",
    "research_assistant.utils",
    "research_assistant.llm", "research_assistant.llm.base",
    "research_assistant.llm.anthropic", "research_assistant.llm.openai_compat",
    "research_assistant.llm.factory",
    "research_assistant.tools", "research_assistant.tools.registry",
    "research_assistant.tools.file_ops", "research_assistant.tools.bash",
    "research_assistant.tools.python_exec",
    "research_assistant.launcher", "research_assistant.launcher_desktop",
    "research_assistant.desktop",
    # pywebview 桌面壳：Windows 后端与 .NET 桥均为运行期动态导入，必须显式声明
    "webview", "webview.platforms.winforms", "webview.platforms.edgechromium",
    "clr_loader", "clr_loader.netfx", "pythonnet", "clr",
]

EXCLUDES = [
    "matplotlib", "numpy", "pandas", "scipy", "PIL", "cv2",
    "torch", "tensorflow", "pytest", "IPython", "notebook", "jupyter",
]


def build(restricted: bool = False, debug_console: bool = False):
    check_env_safety()

    if restricted:
        app_name = "ResearchAssistant_Trial"
        entry = PACKAGE / "launcher_restricted.py"
        print("Building RESTRICTED version (3-month expiry)...\n")
    else:
        app_name = "ResearchAssistant"
        # R7：桌面化入口——单窗口、无黑框、不跳浏览器（D10-D12）
        entry = PACKAGE / "launcher_desktop.py"
        print(f"Building UNRESTRICTED version ({'console' if debug_console else 'noconsole'})...\n")

    datas = _get_datas()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", app_name,
        "--noconfirm", "--clean",
        "--console" if debug_console else "--noconsole",
        "--icon", str(ROOT / "packaging" / "app_icon.ico"),
    ]

    for d in datas:
        cmd.extend(["--add-data", d])
    for imp in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", imp])
    for exc in EXCLUDES:
        cmd.extend(["--exclude-module", exc])

    # pywebview 的 .NET 桥携带数据/二进制（WinForms.dll、WebView2Loader 等），
    # 整体收集以免运行期缺文件
    for pkg in ("webview", "clr_loader", "pythonnet"):
        cmd.extend(["--collect-all", pkg])

    cmd.append(str(entry))

    print(f"  Entry: {entry.name}")
    print(f"  Output: dist/{app_name}/")
    print()

    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode != 0:
        print(f"\nBuild FAILED (exit code {result.returncode})")
        sys.exit(1)

    exe_path = DIST / app_name / f"{app_name}.exe"
    if exe_path.exists():
        print(f"\n{'='*60}")
        print(f"Build SUCCESS! ({'RESTRICTED' if restricted else 'UNRESTRICTED'})")
        print(f"  Output: {exe_path}")
        print(f"  Size:   {exe_path.stat().st_size / 1024 / 1024:.1f} MB")
        if restricted:
            print("  Expiry: 2026-09-15")
        print(f"{'='*60}")

        leaked = _check_for_leaked_keys(DIST / app_name)
        if leaked:
            print("\nWARNING: Potential key leaks:")
            for f in leaked:
                print(f"  - {f}")
        else:
            print("\n[OK] No .env or leaked keys found in output.")
    else:
        print(f"\nBuild completed but exe not found at {exe_path}")


def _check_for_leaked_keys(dist_dir: Path) -> list[str]:
    """扫描产物中是否混入 .env 或疑似密钥串（按前缀+长度泛式匹配，不硬编码具体值）。"""
    leak_pattern = re.compile(r"\b(?:sk-|nvapi-)[A-Za-z0-9_-]{16,}")
    problems = []
    for f in dist_dir.rglob("*"):
        if f.name == ".env" and f.is_file():
            problems.append(str(f))
        if f.suffix in (".json", ".txt", ".cfg", ".ini") and f.is_file():
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                if leak_pattern.search(content):
                    problems.append(f"{f} (contains API key!)")
            except Exception:
                pass
    return problems


if __name__ == "__main__":
    restricted = "--restricted" in sys.argv
    debug_console = "--debug-console" in sys.argv
    build(restricted=restricted, debug_console=debug_console)
