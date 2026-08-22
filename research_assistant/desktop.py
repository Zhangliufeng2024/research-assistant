"""桌面壳（R3）：pywebview 原生窗口包住本地 FastAPI。

零 node 依赖；Windows 一级支持（WebView2 运行时随 Win11 内置），
macOS/Linux 尽力支持。工作区 = 一个文件夹：agent 的读写与产物都落在其中。

用法：
    research-assistant-desktop [工作区目录]

- 不带目录参数时弹原生选夹对话框（tkinter，标准库）；
- 无 GUI / 未安装 pywebview 时打印说明并以 CLI/Web 模式回退（D3 降级路径）；
- 服务只绑定 127.0.0.1 随机端口，随窗口关闭而停止。
"""

import argparse
import os
import socket
import sys
import threading
import time
from pathlib import Path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pick_workspace(initial: str | None) -> str | None:
    """原生选夹对话框；tkinter 不可用或用户取消返回 None。"""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(
            title="选择工作区文件夹", initialdir=initial or os.getcwd())
        root.destroy()
        return chosen or None
    except Exception as e:  # 无显示环境等
        print(f"[desktop] 文件夹选择器不可用（{e}），改用当前目录。", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Research Assistant Desktop")
    parser.add_argument("workspace", nargs="?", help="工作区目录（缺省弹选夹）")
    args = parser.parse_args()

    workspace = args.workspace
    if workspace:
        workspace = str(Path(workspace).expanduser().resolve())
        if not Path(workspace).is_dir():
            print(f"[desktop] 目录不存在：{workspace}", file=sys.stderr)
            return 2
    else:
        workspace = _pick_workspace(os.getcwd())
        if workspace is None and not sys.stdin.isatty():
            return 2
        if not workspace:
            workspace = os.getcwd()
    os.chdir(workspace)

    try:
        import webview  # pywebview
    except ImportError:
        print("[desktop] 未安装 pywebview，无法启动桌面窗口。\n"
              "           安装：pip install 'research-assistant[desktop]'\n"
              "           回退：research-assistant-web 直接使用浏览器模式。",
              file=sys.stderr)
        return 2

    # ---- 后台起本地服务（随机端口，仅回环）----
    import uvicorn

    from .web.app import create_app

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(
        create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        if not thread.is_alive():
            print("[desktop] 本地服务启动失败，详见上方日志。", file=sys.stderr)
            return 1
        time.sleep(0.1)
    if not server.started:
        print("[desktop] 本地服务启动超时。", file=sys.stderr)
        return 1

    # ---- 主线程跑窗口（pywebview 要求主线程）----
    webview.create_window(
        "研究助手 · RA Console",
        f"http://127.0.0.1:{port}",
        width=1440, height=900, min_size=(1024, 640))
    try:
        webview.start()
    except Exception as e:
        print(f"[desktop] 窗口启动失败（{e}）。\n"
              f"           回退：浏览器打开 http://127.0.0.1:{port}",
              file=sys.stderr)
        try:  # 窗口起不来时保底把服务拉到前台供浏览器访问
            while thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return 1
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
