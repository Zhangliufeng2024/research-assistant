"""Build script — creates standalone Windows .exe via PyInstaller.

R7 起默认打包为**无黑框桌面应用**（--noconsole，单窗口 pywebview 壳，
诊断走 <工作区>/.ra/logs/desktop.log）。调试时可加 --debug-console 保留控制台。

Usage:
    python build.py                    # 无控制台桌面版（发布用）
    python build.py --debug-console    # 保留控制台的调试版
    python build.py --restricted       # trial-branded entry (no expiry gate)

打包前置检查（任一失败即中止）：
    1. 四处版本号一致：pyproject.toml / __init__.py / installer.iss / package.json
    2. 源码树密钥泄漏扫描（文本 + 二进制，含 dist/ 旧产物）
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
DIST = ROOT / "dist"
BUILD = ROOT / "build"
PACKAGE = ROOT / "research_assistant"


# ---------------------------------------------------------------------------
# 版本一致性检查
# ---------------------------------------------------------------------------

def _read_versions() -> dict[str, str | None]:
    """提取四处版本号；解析不到的记为 None（简单正则即可，不引入新依赖）。"""
    out: dict[str, str | None] = {}

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject)
    out["pyproject.toml"] = m.group(1) if m else None

    init_py = (PACKAGE / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'(?m)^__version__\s*=\s*"([^"]+)"', init_py)
    out["research_assistant/__init__.py"] = m.group(1) if m else None

    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    m = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', iss)
    out["packaging/installer.iss"] = m.group(1) if m else None

    pkg = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    v = pkg.get("version")
    out["frontend/package.json"] = str(v) if v else None

    return out


def _fail_if_inconsistent(versions: dict[str, str | None]) -> None:
    bad = {k: v for k, v in versions.items() if not v}
    if bad:
        print("ERROR: 无法解析以下文件的版本号，请人工核对：")
        for k in bad:
            print(f"  - {k}")
        sys.exit(1)

    distinct = sorted(set(versions.values()))
    print("  Version sources:")
    for k, v in versions.items():
        print(f"    - {k}: {v}")
    if len(distinct) > 1:
        print(f"\nERROR: 版本号不一致（{' vs '.join(distinct)}）—— 请先统一四处版本再打包。")
        sys.exit(1)
    print(f"[OK] 四处版本一致: {distinct[0]}\n")


def check_version_consistency():
    _fail_if_inconsistent(_read_versions())


# ---------------------------------------------------------------------------
# 泄漏扫描（文本 + 二进制）
# ---------------------------------------------------------------------------

# 文本扫描扩展名；二进制做字节级正则扫描的扩展名
TEXT_EXTS = {
    ".py", ".md", ".txt", ".cfg", ".ini", ".json",
    ".yaml", ".yml", ".toml", ".html", ".js", ".ts",
}
BINARY_EXTS = {".exe", ".dll", ".pyd", ".pyc", ".pyz"}

KEY_RE_TEXT = re.compile(r"\b(?:sk-|nvapi-)[A-Za-z0-9_-]{16,}")
KEY_RE_BYTES = (
    re.compile(rb"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(rb"\bnvapi-[A-Za-z0-9_-]{16,}"),
)

# 目录剪枝：node_modules/.git 按规约排除（dist **不排除**，同样要扫）；
# 虚拟环境是第三方 site-packages——体积大、示例假钥匙多，纯噪声；
# tests/ 的夹具故意放假钥匙（sk- 加一串字母表序号那种），且测试代码从不入包。
SCAN_SKIP_DIRS = {"node_modules", ".git", ".venv", "venv"}

# 明显占位符样例不算泄漏（技能文档/示例里常见 your_key_here、<your-key> 之类；
# 这些文档会随 .claude/ 打入安装包，若不过滤则每次构建都会误报）。
PLACEHOLDER_MARKS = ("your", "here", "example", "placeholder", "dummy", "xxx")

_CHUNK = 1024 * 1024   # 二进制分块大小
_OVERLAP = 4096        # 块间重叠，覆盖跨块边界的匹配


def _mask(fragment: str) -> str:
    if len(fragment) <= 8:
        return "****"
    return f"{fragment[:4]}****{fragment[-4:]}"


def _is_placeholder(fragment: str) -> bool:
    low = fragment.lower()
    return any(mark in low for mark in PLACEHOLDER_MARKS)


def _scan_file_for_keys(path: Path) -> list[str]:
    """返回该文件中疑似真实密钥的片段（已去重、已滤除占位符样例）。"""
    ext = path.suffix.lower()
    found: list[str] = []
    try:
        if ext in TEXT_EXTS:
            found = KEY_RE_TEXT.findall(path.read_text(encoding="utf-8", errors="ignore"))
        elif ext in BINARY_EXTS:
            tail = b""
            with path.open("rb") as fh:
                while True:
                    chunk = fh.read(_CHUNK)
                    if not chunk:
                        break
                    data = tail + chunk
                    for pat in KEY_RE_BYTES:
                        found.extend(
                            m.decode("ascii", "ignore") for m in pat.findall(data)
                        )
                    tail = data[-_OVERLAP:]
        else:
            return []
    except OSError:
        return []
    return [f for f in dict.fromkeys(found) if not _is_placeholder(f)]


def _scan_leaked_keys(root: Path, skip_extra: frozenset[str] = frozenset()) -> list[tuple[Path, str]]:
    """在 root 下递归扫描疑似密钥，返回 [(文件, 片段), ...]。"""
    skip = SCAN_SKIP_DIRS | skip_extra
    problems: list[tuple[Path, str]] = []
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in skip:
                    stack.append(entry)
            elif entry.is_file():
                for frag in _scan_file_for_keys(entry):
                    problems.append((entry, frag))
    return problems


def _display_path(p: Path) -> Path:
    try:
        return p.relative_to(ROOT)
    except ValueError:
        return p


def check_env_safety():
    """打包前安全检查：.env 提醒 + 全仓（含 dist/）密钥泄漏扫描。"""
    warned = False
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
                warned = True
                break

    # 预检扫描整个仓库（dist/ 旧产物一并扫）；tests/ 剪枝理由见 SCAN_SKIP_DIRS 上方注释
    problems = _scan_leaked_keys(ROOT, skip_extra=frozenset({"tests"}))
    if problems:
        print("\nERROR: 源码树中发现疑似真实密钥，构建中止：")
        for f, frag in problems:
            print(f"  - {_display_path(f)} -> {_mask(frag)}")
        sys.exit(1)

    if warned:
        # .env 允许存在用户自己的密钥（不会被打包），只提醒、不放行标记
        print("[NOTE] .env 密钥扫描通过（.env 本身不入包，见上方提醒）。")
    print("[OK] .env safety check passed.\n")


def _get_datas():
    static_dir = PACKAGE / "web" / "static"
    claude_dir = PACKAGE / ".claude"
    root_claude_dir = ROOT / ".claude"

    if not static_dir.exists():
        print(f"ERROR: {static_dir} not found!")
        sys.exit(1)

    # 打包副本放到系统临时目录，避免每次构建在项目 build/ 内留下
    # 需要批量删除的旧副本（会触发环境的 bulk-delete 确认而中止构建）。
    clean_claude_dir = Path(tempfile.mkdtemp(prefix="ra_claude_clean_"))

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
    "dotenv", "docx", "docx.opc", "docx.opc.constants",
    "research_assistant", "research_assistant.web",
    "research_assistant.web.app", "research_assistant.web.routes", "research_assistant.web.ws",
    # R18 提示词增强端点。web/prompt.py 已由 app.py 静态导入（PyInstaller 能自动
    # 收集），显式声明只为与 settings/workspace 等 web 子模块保持同一口径。
    "research_assistant.web.prompt",
    "research_assistant.api", "research_assistant.agent", "research_assistant.cli",
    "research_assistant.config", "research_assistant.core", "research_assistant.constants",
    "research_assistant.models", "research_assistant.docgen", "research_assistant.orchestrator",
    "research_assistant.retry", "research_assistant.display", "research_assistant.steer",
    "research_assistant.utils",
    "research_assistant.runtime", "research_assistant.runtime.platform_store",
    "research_assistant.runtime.task_hub", "research_assistant.runtime.scheduler",
    "research_assistant.context", "research_assistant.context.sources",
    "research_assistant.artifacts", "research_assistant.artifacts.versioning",
    "research_assistant.workflows", "research_assistant.workflows.registry",
    "research_assistant.workflows.runner",
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

# R8 反馈 #4（cowork 交付物）：numpy/pandas/matplotlib/PIL 不再排除——
# 冻结版 run_python 走进程内执行器（tools/frozen_exec.py），会话里能真正
# 画图与跑数据分析。代价是体积增加约 60-90MB（压缩后）。scipy/cv2/深度
# 学习框架仍然排除（体积失控且研究助手场景极少用到）。
HIDDEN_IMPORTS += ["numpy", "pandas", "matplotlib", "PIL"]

# R13 打包瘦身：
# - llvmlite/numba/shap 在全代码库零真实 import（此前的 grep 命中均为
#   "shape" 单词误匹配），是 PyInstaller 依赖分析误卷入的死重（约 ~102MB）；
# - pymupdf/fitz 仅 .claude 技能脚本（pdf_to_images.py）可选使用，缺库时
#   自带降级分支；核心 PDF 文本处理走 pypdf。打包版不含 pymupdf，需要
#   PDF→图片转换时在开发环境安装，或使用 pyproject 的 [pdf-images] extra。
EXCLUDES = [
    "scipy", "cv2",
    "torch", "tensorflow", "pytest", "IPython", "notebook", "jupyter",
    "llvmlite", "numba", "shap",
    "pymupdf", "fitz",
]


def build(restricted: bool = False, debug_console: bool = False):
    check_version_consistency()
    check_env_safety()

    if restricted:
        app_name = "ResearchAssistant_Trial"
        entry = PACKAGE / "launcher_restricted.py"
        print("Building RESTRICTED version (trial-branded entry, expiry gate removed)...\n")
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
        print(f"{'='*60}")

        leaked = _check_for_leaked_keys(DIST / app_name)
        if leaked:
            print("\nERROR: 打包产物中发现疑似密钥泄漏，按发布流程应作废本产物：")
            for f, frag in leaked:
                print(f"  - {_display_path(f)} -> {_mask(frag)}")
            sys.exit(1)
        print("\n[OK] No .env or leaked keys found in output.")
    else:
        print(f"\nBuild completed but exe not found at {exe_path}")


def _check_for_leaked_keys(dist_dir: Path) -> list[tuple[Path, str]]:
    """扫描产物中是否混入 .env 或疑似密钥串（文本全量 + 二进制字节级，泛式匹配）。"""
    problems = _scan_leaked_keys(dist_dir)
    for f in dist_dir.rglob(".env"):
        if f.is_file():
            problems.append((f, "<.env file bundled>"))
    return problems


if __name__ == "__main__":
    restricted = "--restricted" in sys.argv
    debug_console = "--debug-console" in sys.argv
    build(restricted=restricted, debug_console=debug_console)
