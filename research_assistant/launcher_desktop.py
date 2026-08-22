"""PyInstaller 冻结入口（R7 D10-D12）：无黑框、单窗口桌面模式。

build.py 以 --noconsole 打包本文件；所有诊断走 desktop.setup_logging 的
文件日志与 tkinter 错误框，不再依赖控制台。
"""

import sys

from research_assistant.desktop import main

if __name__ == "__main__":
    sys.exit(main())
