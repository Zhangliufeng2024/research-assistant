"""冻结环境（PyInstaller）内的 Python 代码执行器——spawn 子进程隔离。

冻结版没有独立解释器可调（``sys.executable`` 是应用自身），再拿它跑
脚本等于重启整个应用。因此用 ``multiprocessing``（spawn）从应用自身派生
一个**干净子进程**执行用户代码：

- 可强杀：超时 ``kill()``,死循环不再拖垮应用（线程方案杀不掉且会偷 GIL，
  实测把整个事件循环拖慢百倍，已废弃）；
- 无副作用：os.chdir / stdout 重定向只发生在子进程内；
- 打包进来的 numpy / pandas / matplotlib 直接可用（build.py R8 起不再
  排除），会话里能真正画图、跑分析（R8 反馈 #4 cowork 交付物）。

前提：入口必须调用 ``multiprocessing.freeze_support()``（desktop.main
第一行已做）——否则冻结子进程会重新启动整个桌面应用。
"""

import asyncio
import multiprocessing
import os
import sys
import tempfile
import traceback
from pathlib import Path

from ..constants import OUTPUT_TRUNCATION_HALF, OUTPUT_TRUNCATION_LIMIT

#: 子进程 join 的额外宽限（秒）：join 自带超时，这里只是防御性余量。
_JOIN_GRACE_S = 10


def _child_main(code: str, cwd: str, out_path: str) -> None:
    """子进程入口：执行用户代码，stdout/stderr 全量写入 out_path。"""
    os.environ.setdefault("MPLBACKEND", "Agg")  # 无头：savefig 可用，show 不阻塞
    os.chdir(cwd)
    with open(out_path, "w", encoding="utf-8") as fh:
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = fh
        sys.stderr = fh
        try:
            globs = {
                "__name__": "__main__",
                "__file__": os.path.join(cwd, "_ra_exec.py"),
            }
            try:
                exec(compile(code, "_ra_exec.py", "exec"), globs)  # noqa: S102
            except SystemExit as e:  # 用户脚本 sys.exit：按正常退出汇报
                print(f"(exit: {e.code})")
            except BaseException:
                traceback.print_exc(file=sys.stderr)
        finally:
            try:
                fh.flush()
            except Exception:
                pass
            sys.stdout, sys.stderr = old_out, old_err


async def run_python_inprocess(code: str, timeout: int = 120, cwd: str = ".") -> str:
    """在 spawn 子进程中执行 Python 代码，返回 stdout + stderr（超时强杀）。"""
    work_dir = Path(cwd).resolve()
    if not work_dir.is_dir():
        return f"Error: working directory does not exist: {work_dir}"

    fd, out_path = tempfile.mkstemp(
        prefix="_ra_exec_out_", suffix=".txt", dir=str(work_dir))
    os.close(fd)

    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(
        target=_child_main, args=(code, str(work_dir), out_path), daemon=True)
    proc.start()

    # join 阻塞放进工作线程，避免卡住事件循环；join 自身限时返回
    await asyncio.to_thread(proc.join, timeout)
    timed_out = proc.is_alive()
    if timed_out:
        proc.kill()
        await asyncio.to_thread(proc.join, _JOIN_GRACE_S)

    try:
        result = Path(out_path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        result = ""
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass

    if timed_out:
        result = (
            f"{result}\n\nError: Python code timed out after {timeout} "
            "seconds (process terminated)"
        ).strip()
    if len(result) > OUTPUT_TRUNCATION_LIMIT:
        result = (
            result[:OUTPUT_TRUNCATION_HALF]
            + "\n\n... (output truncated) ...\n\n"
            + result[-OUTPUT_TRUNCATION_HALF:]
        )
    return result or "(no output)"
