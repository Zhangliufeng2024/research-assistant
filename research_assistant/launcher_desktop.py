"""PyInstaller 冻结入口（R7 D10-D12）：无黑框、单窗口桌面模式。

build.py 以 --noconsole 打包本文件；所有诊断走 desktop.setup_logging 的
文件日志与 tkinter 错误框，不再依赖控制台。

R8：``freeze_support()`` 必须最先调用——frozen_exec 用 spawn 子进程执行
用户代码（run_python），没有这一行，派生出的子进程会重新启动整个桌面应用。
"""

import multiprocessing
import sys

from research_assistant.desktop import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
