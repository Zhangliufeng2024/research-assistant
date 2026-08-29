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
import logging
import multiprocessing
import os
import sys
import tempfile
import traceback
from pathlib import Path

from ..constants import truncate_tool_output
from .exec_provider import sanitized_exec_env

#: 子进程 join 的额外宽限（秒）：join 自带超时，这里只是防御性余量。
_JOIN_GRACE_S = 10

logger = logging.getLogger(__name__)


def _make_script_runner():
    """构造注入给用户代码的 ``run_script(path, argv=None)`` 助手。

    冻结态没有独立解释器，技能脚本（generate_schematic.py 等）不能再经
    subprocess 跑——本助手在子进程内就地执行脚本文件：正确设置
    ``sys.argv`` / ``__name__`` / ``__file__`` 并把脚本目录插到
    ``sys.path[0]``（兄弟模块可导入），结束后全部恢复。脚本内 SystemExit
    与异常按 _child_main 同样口径汇报、不炸外层代码。
    """

    def run_script(path, argv=None):  # noqa: ANN001, ANN202
        p = Path(str(path)).expanduser()
        if not p.is_file():
            return (
                f"Error: script not found: {path}\n"
                "请用绝对路径定位脚本（工作区根见全局常量 WS；"
                "不要用 bash/subprocess 调 python）。"
            )
        resolved = p.resolve()
        source = resolved.read_text(encoding="utf-8")
        old_argv = list(sys.argv)
        old_path = list(sys.path)
        try:
            sys.argv = [str(resolved), *(str(a) for a in (argv or []))]
            sys.path.insert(0, str(resolved.parent))
            # 自注入：脚本内可再嵌套 run_script（与顶层代码同一能力面）
            globs = {"__name__": "__main__", "__file__": str(resolved), "run_script": run_script}
            try:
                exec(compile(source, str(resolved), "exec"), globs)  # noqa: S102
            except SystemExit as e:
                print(f"(exit: {e.code})")
            except BaseException:
                traceback.print_exc(file=sys.stderr)
        finally:
            sys.argv = old_argv
            sys.path[:] = old_path

    return run_script


def _child_main(code: str, cwd: str, out_path: str, workspace_root: str = "") -> None:
    """子进程入口：执行用户代码，stdout/stderr 全量写入 out_path。

    A+ 阶段 5 / G-4（frozen_exec 收口）：spawn 子进程**继承父进程完整环境**，
    而 ``multiprocessing.Process`` 不暴露 env 参数，无法像 ``_run_process``
    那样在启动前换掉。因此在执行模型代码**之前**由子进程自净——
    ``_run_script_in_process`` 走的也是这条路（它同样继承完整环境）。

    注意必须在 ``exec`` 之前完成：一旦模型代码开始跑，任何净化都太晚了。

    ⚠️ 顺序陷阱：**必须先取净化快照，再 clear**。``sanitized_exec_env()``
    缺省读的就是 ``os.environ``——若先 ``clear()`` 再调它，拿到的是空表，
    子进程只剩一个变量，matplotlib 等库会因找不到 HOME/USERPROFILE 直接崩
    （本轮实现时就踩了：实测 N=1）。
    """
    cleaned = sanitized_exec_env()
    os.environ.clear()
    os.environ.update(cleaned)
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
                # R12 P1：打包态执行契约的运行时半边——WS=工作区根常量，
                # run_script 就地执行 .py 脚本（替代被禁的 bash python）
                "WS": workspace_root,
                "run_script": _make_script_runner(),
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
                pass  # 尽力而为：输出重定向恢复前的最后一次冲刷，失败不掩盖用户脚本结果
            sys.stdout, sys.stderr = old_out, old_err


async def run_python_inprocess(
    code: str,
    timeout: int = 120,
    cwd: str = ".",
    workspace_root: str | None = None,
) -> str:
    """在 spawn 子进程中执行 Python 代码，返回 stdout + stderr（超时强杀）。

    ``workspace_root``：工作区根绝对路径，作为子进程内全局常量 ``WS``
    暴露（不能从 cwd 推导——会话模式下 cwd 是产物目录而非根）。
    """
    work_dir = Path(cwd).resolve()
    if not work_dir.is_dir():
        return f"Error: working directory does not exist: {work_dir}"

    fd, out_path = tempfile.mkstemp(
        prefix="_ra_exec_out_", suffix=".txt", dir=str(work_dir))
    os.close(fd)

    # 窗口闪烁结论（Bug B 排查证据）：CPython 的 spawn 启动器
    # （multiprocessing/popen_spawn_win32.Popen._launch，3.13 实读确认）调用
    # ``_winapi.CreateProcess`` 时 creationflags=0（仅 STARTF_FORCEOFFFEEDBACK），
    # 且 multiprocessing.Process 不向用户暴露 creationflags 参数——此处无法
    # 传 CREATE_NO_WINDOW。不会闪窗的依据：发布构建为 --noconsole（GUI 子
    # 系统，见 build.py R7），GUI 子系统进程经 CreateProcess 派生时**不自动
    # 分配控制台**——子进程（同一 exe）继承父进程的无窗状态；--debug-console
    # 构建与开发态下子进程直接继承父控制台，同样无新窗。注意若未来改回
    # console 子系统构建，flags=0 的 spawn 子进程会闪独立控制台窗，需重评。
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(
        target=_child_main,
        args=(code, str(work_dir), out_path, workspace_root or ""),
        daemon=True)
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
            # 修复 E：清理失败不再静默 pass——留 WARNING 供诊断（文件被占用等）
            logger.warning(
                "清理子进程输出临时文件失败: %s", out_path, exc_info=True)

    if timed_out:
        result = (
            f"{result}\n\nError: Python code timed out after {timeout} "
            "seconds (process terminated)"
        ).strip()
    elif proc.exitcode not in (0, None):
        # 修复 E：_child_main 捕获了脚本异常，正常路径 exitcode 恒为 0；
        # 非 0 只可能是子进程级故障（os._exit / native 崩溃 / 内存耗尽），
        # 此时输出可能为空或不完整，必须显式回报而不是静默成功。
        result = f"{result}\n\n[执行器] 子进程异常退出，exitcode={proc.exitcode}".strip()
    result = truncate_tool_output(result)
    return result or "(no output)"
