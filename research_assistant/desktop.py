"""桌面壳（R3 建立骨架，R7 桌面化，R8 免选夹直入）：pywebview 原生窗口包住本地 FastAPI。

目标形态（R7 D10-D12 + R8 反馈 #1）——正式桌面应用：
- **单窗口**：原生窗口即应用，不打开浏览器、不弹黑色控制台；
- **零打断启动**：首次使用不再弹选夹——自动落默认工作区（文档/研究助手）
  安静开工；换目录是界面内的事（会话页工作目录入口 / POST /api/workspace/root）；
- **无黑框**：PyInstaller 以 --noconsole 冻结，所有诊断写入文件日志；
- **可诊断**：日志落在 `<工作区>/.ra/logs/desktop.log`，启动失败弹原生错误框；
- **零依赖门槛**：Windows 启动前检测 WebView2 运行时，缺失时给出图形化指引。

用法：
    research-assistant-desktop [工作区目录]

- 不带目录参数时优先复用上次的工作区（记忆在 %APPDATA%/ResearchAssistant/
  desktop.json），无记忆则用默认目录（文档/研究助手，不存在即创建）；
- 服务只绑定 127.0.0.1 随机端口，随窗口关闭而停止；
- 通过 js_api 向前端暴露 DesktopBridge（原生选夹等能力）。
"""

import argparse
import json
import logging
import multiprocessing
import os
import socket
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_DATA_DIR = (
    Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "ResearchAssistant"
)
WORKSPACE_FILE = APP_DATA_DIR / "desktop.json"

#: 无记忆时的缺省工作区名（落在「文档」下；不可得则退回家目录）。
DEFAULT_WORKSPACE_NAME = "研究助手"

LOG = logging.getLogger("ra.desktop")


# ---------------------------------------------------------------- 日志 ----


def setup_logging(workspace: Path) -> Path:
    """文件日志：<workspace>/.ra/logs/desktop.log（滚动 1MB × 3）。

    --noconsole 冻结后没有可见控制台，这是唯一的诊断出口，必须尽早建立。
    """
    log_dir = workspace / ".ra" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "desktop.log"

    handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    LOG.info("=== Research Assistant desktop 启动 ===")
    LOG.info("workspace=%s frozen=%s", workspace, bool(getattr(sys, "frozen", False)))
    return log_file


# ------------------------------------------------------------ GUI 提示框 ----


def _tk_root():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    return root


def gui_error(title: str, msg: str) -> None:
    """原生错误对话框；tkinter 不可用时退化为仅写日志。"""
    LOG.error("GUI error: %s | %s", title, msg.replace("\n", " ⏎ "))
    try:
        from tkinter import messagebox

        root = _tk_root()
        messagebox.showerror(title, msg, parent=root)
        root.destroy()
    except Exception as e:  # pragma: no cover - 无显示环境
        LOG.error("无法弹出错误框：%s", e)


def gui_confirm(title: str, msg: str) -> bool:
    """原生是/否对话框；不可用时视为否。"""
    try:
        from tkinter import messagebox

        root = _tk_root()
        ans = messagebox.askyesno(title, msg, parent=root)
        root.destroy()
        return ans
    except Exception as e:  # pragma: no cover
        LOG.error("无法弹出确认框：%s", e)
        return False


# --------------------------------------------------------- WebView2 检测 ----

_WEBVIEW2_KEY = r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def webview2_runtime_missing() -> bool:
    """检测 WebView2 Evergreen 运行时（仅 Windows 有意义）。

    依次查：用户显式指定的 WEBVIEW2_BROWSER_EXECUTABLE_FOLDER → 注册表
    HKLM/HKCU ×（WOW6432Node 与原生视图）。找不到固定 GUID 的 pv 值即视为缺失。
    """
    if sys.platform != "win32":
        return False
    if os.environ.get("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER"):
        return False

    try:
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
                try:
                    with winreg.OpenKey(hive, _WEBVIEW2_KEY, 0, winreg.KEY_READ | view) as key:
                        pv = winreg.QueryValueEx(key, "pv")[0]
                    if pv and pv != "0.0.0.0":
                        return False
                except OSError:
                    continue
    except ImportError:  # 非 Windows（不会到这里）
        return False
    return True


def guide_webview2_install() -> None:
    """D12：运行时缺失时的图形化指引——说明 + 可选打开官方下载页。"""
    LOG.warning("WebView2 运行时未检出")
    opened = gui_confirm(
        "研究助手 · 需要一次性的系统组件",
        "运行桌面窗口需要 Microsoft WebView2 运行时。\n\n"
        "Windows 11 通常已内置；你的系统似乎缺少该组件。\n"
        "点击「是」将打开微软官网下载页（Evergreen 引导程序，约 2MB，\n"
        "安装完成后重新启动本应用即可）。",
    )
    if opened:
        import webbrowser

        webbrowser.open("https://developer.microsoft.com/microsoft-edge/webview2/")


# ----------------------------------------------------------- 工作区记忆 ----


def default_workspace() -> Path:
    """缺省工作区：文档/研究助手（文档目录不可得则退回用户家目录）。"""
    docs = Path.home() / "Documents"
    base = docs if docs.is_dir() else Path.home()
    return base / DEFAULT_WORKSPACE_NAME


def load_last_workspace() -> str | None:
    try:
        data = json.loads(WORKSPACE_FILE.read_text(encoding="utf-8"))
        p = data.get("last_workspace")
        if p and Path(p).is_dir():
            return p
    except Exception:
        pass
    return None


def remember_workspace(path: str) -> None:
    try:
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        WORKSPACE_FILE.write_text(
            json.dumps({"last_workspace": path}, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        LOG.warning("无法记住工作区：%s", e)


def pick_workspace(initial: str | None) -> str | None:
    """原生选夹对话框；tkinter 不可用或用户取消返回 None。"""
    try:
        from tkinter import filedialog

        root = _tk_root()
        chosen = filedialog.askdirectory(
            title="选择工作目录（研究产物将保存在这里）", initialdir=initial or os.getcwd()
        )
        root.destroy()
        return chosen or None
    except Exception as e:
        LOG.error("文件夹选择器不可用：%s", e)
        return None


class DesktopBridge:
    """暴露给前端 ``window.pywebview.api`` 的原生能力桥（R8 反馈 #1）。

    前端经 ``window.pywebview.api.<方法>()`` 调用（Promise 语义）；浏览器
    直连等非 pywebview 环境没有该对象，前端自动降级为手动输入路径。方法
    由 pywebview 在工作线程执行——Windows 下 tkinter 对话框可安全创建于
    非主线程；任何异常一律降级为空串/None 返回，绝不阻塞 UI。
    """

    def ping(self) -> str:
        """连通性探测：前端据此判断原生桥是否已注入。"""
        return "ok"

    def select_folder(self, title: str = "") -> str:
        """系统选夹对话框；取消或失败返回空串。选中即更新工作区记忆。"""
        try:
            chosen = pick_workspace(os.getcwd())
            if chosen:
                remember_workspace(chosen)
                LOG.info("select_folder: %s (%s)", chosen, title or "-")
            return chosen or ""
        except Exception as e:
            LOG.error("select_folder 失败：%s", e)
            return ""


_LEGACY_CONFIG_KEYS = (
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_PROVIDER",
    "IMAGE_API_KEY",
    "IMAGE_BASE_URL",
    "IMAGE_MODEL",
    "IMAGE_REVIEW_MODEL",
    "PARALLEL_API_KEY",
    "SEMANTIC_SCHOLAR_API_KEY",
)


def migrate_legacy_config() -> None:
    """v3.2.0 → R7/R8 升级兼容（一次性、单向）。

    旧版桌面端把模型密钥存在 %APPDATA%/ResearchAssistant/config.json；
    R8 起设置页统一写**全局** ``%APPDATA%/ResearchAssistant/.env``（切换
    工作目录不丢）。仅当全局文件还没有 LLM_API_KEY 时才迁移，绝不覆盖
    用户已有配置。（v3.3.0 存在「工作区 .env」里的配置由
    ``config.ensure_global_config`` 负责上移，两条迁移互不重叠。）
    """
    try:
        from .config import app_config_env_path

        env_file = app_config_env_path()
        if env_file.exists():
            for raw in env_file.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    if k.strip() == "LLM_API_KEY" and v.strip():
                        return  # 全局已配置，不动

        cfg_file = APP_DATA_DIR / "config.json"
        if not cfg_file.exists():
            return
        legacy = json.loads(cfg_file.read_text(encoding="utf-8"))
        pairs = [(k, str(legacy[k]).strip()) for k in _LEGACY_CONFIG_KEYS if legacy.get(k)]
        if not any(k.startswith("LLM_") for k, _ in pairs):
            return

        with open(env_file, "a", encoding="utf-8") as f:
            if env_file.exists() and env_file.stat().st_size > 0:
                f.write("\n")
            f.write("# 迁移自 v3.2.0 桌面配置（%APPDATA%/ResearchAssistant/config.json）\n")
            for k, v in pairs:
                f.write(f"{k}={v}\n")
        LOG.info("已从旧版 config.json 迁移 %d 个配置键到全局 .env", len(pairs))
    except Exception as e:
        LOG.warning("旧配置迁移跳过：%s", e)


# ---------------------------------------------------------------- 主流程 ----


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def bundle_root() -> Path:
    """冻结版返回解包目录（含打包进来的 .claude 技能），开发态返回仓库根。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).parent.parent


def main() -> int:
    # spawn 子进程引导（frozen_exec 的 run_python 派生进程会再次执行本入口，
    # 靠这行走入 multiprocessing bootstrap 而非重启桌面应用）；常规启动是 no-op。
    multiprocessing.freeze_support()

    # WebView2 只访问本地回环服务，页面资源全在本地——系统代理对它毫无用处，
    # 反而在某些 PAC/企业代理配置下拦截回环 WebSocket（R9 用户环境排查项）。
    # 加载器原生支持该环境变量，等价于给浏览器加 --no-proxy-server。
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--no-proxy-server")

    parser = argparse.ArgumentParser(description="Research Assistant Desktop")
    parser.add_argument("workspace", nargs="?", help="工作区目录（缺省用上次记忆或默认目录）")
    args = parser.parse_args()

    # ---- 解析工作区（此阶段尚无文件日志，出错只能靠弹框）----
    # R8 反馈 #1：首次启动不再弹选夹。优先级 CLI 参数 > 上次记忆 > 默认目录
    # （文档/研究助手，不存在即创建）。换目录改为界面内操作。
    if args.workspace:
        candidate = str(Path(args.workspace).expanduser().resolve())
        if not Path(candidate).is_dir():
            gui_error("研究助手", f"目录不存在：\n{candidate}")
            return 2
    else:
        remembered = load_last_workspace()
        candidate = remembered or str(default_workspace())

    try:
        Path(candidate).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        gui_error("研究助手", f"无法准备工作目录：\n{candidate}\n\n{e}")
        return 2

    os.chdir(candidate)
    workspace_path = Path(candidate).resolve()

    # ---- 从这里起有日志了 ----
    log_file = setup_logging(workspace_path)
    remember_workspace(str(workspace_path))

    try:
        (workspace_path / "writing_outputs").mkdir(exist_ok=True)
        from .config import ensure_global_config

        ensure_global_config(workspace_path)  # v3.3.0 工作区配置一次性上移全局
        migrate_legacy_config()  # v3.2.0 config.json → 全局 .env

        # 同步内置技能到工作区（冻结包内 .claude → <workspace>/.claude，
        # 与 create_app 的 lifespan 中 package_dir 同步互补：冻结时包目录不含根级 .claude）
        from .core import setup_claude_skills

        setup_claude_skills(bundle_root(), workspace_path)
        LOG.info("技能同步完成")

        import webview  # pywebview

        if webview2_runtime_missing():
            guide_webview2_install()
            return 3

        # ---- 后台起本地服务（随机端口，仅回环）----
        import uvicorn

        from .web.app import create_app

        port = _free_port()
        server = uvicorn.Server(
            uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        deadline = time.time() + 15
        while not server.started and time.time() < deadline:
            if not thread.is_alive():
                gui_error(
                    "研究助手 · 启动失败", f"本地服务未能启动，请把日志发给开发者：\n{log_file}"
                )
                return 1
            time.sleep(0.1)
        if not server.started:
            gui_error("研究助手 · 启动超时", f"本地服务 15 秒内未就绪，请查看日志：\n{log_file}")
            return 1

        LOG.info("服务就绪 http://127.0.0.1:%d，打开主窗口", port)

        # ---- 主线程跑窗口（pywebview 要求主线程）；js_api 暴露原生选夹 ----
        bridge = DesktopBridge()
        webview.create_window(
            "研究助手 · Research Assistant",
            f"http://127.0.0.1:{port}",
            width=1440,
            height=900,
            min_size=(1024, 640),
            js_api=bridge,
        )
        try:
            webview.start()
            LOG.info("主窗口关闭，退出")
        except Exception as e:
            LOG.exception("窗口启动失败")
            gui_error("研究助手 · 无法创建窗口", f"{e}\n\n请查看日志了解详情：\n{log_file}")
            return 1
        finally:
            server.should_exit = True
            thread.join(timeout=5)
        return 0
    except SystemExit:
        raise
    except Exception:
        LOG.exception("未捕获异常")
        gui_error("研究助手 · 发生错误", f"发生未预期的错误，请把日志发给开发者：\n{log_file}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
