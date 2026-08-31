"""Bash command execution tool."""

import asyncio
import locale
import os
import re
import subprocess
import sys

from ..constants import truncate_tool_output
from .exec_provider import sanitized_exec_env

#: 冻结态拦截的可执行名（小写、去 .exe；python* 前缀另行匹配）。
_PY_INVOKABLE = frozenset({"python", "python3", "py", "pip", "pip3"})

_FROZEN_PY_GUARD_MSG = (
    "[打包环境] 本机没有独立 Python，无法在 bash 里执行 python/pip 命令——"
    "sys.executable 是本应用自身，启动它会重启整个桌面应用。\n"
    "请改用：\n"
    "- Python 代码 / matplotlib 画图：run_python 工具（内置 numpy/pandas/matplotlib）\n"
    "- 运行 .py 脚本文件：run_python 内调用 run_script(绝对路径, argv=[...])"
)

_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# \r\n 也算段分隔符：cmd.exe 会把裸 LF 当命令分隔符，不切行就会漏检
# 「dir\npython x.py」这类换行藏毒的复合命令（冻结态拦截加固 ①）。
_SEG_SPLIT_RE = re.compile(r"&&|\|\||[|&;\r\n]")

# call/start/cmd 前缀：其后可能跟着 / 开关与带引号窗口标题，需跳过后再判
# 命令本体，否则「call python -V」「start "" python x.py」直接放行（加固 ③）。
_CMD_PREFIX_TOKENS = frozenset({"call", "start", "cmd", "cmd.exe"})
_PREFIX_MAX_DEPTH = 4  # call cmd /c python … 的前缀链防御性深度上限

#: P1-6：这些命令的**后续参数**是文本/文件路径而非可执行名——其中出现
#: ``python`` 字样不算调用（``grep python notes.txt``、``where python``）。
#: 仅比对紧邻前一个 token：前缀链外的包装器（wsl/pwsh/conhost/…）不在表里，
#: 其后的 python 正常命中。
_ARG_CONSUMERS = frozenset({
    "grep", "egrep", "fgrep", "findstr", "find", "echo", "type", "cat",
    "less", "more", "head", "tail", "wc", "sort", "uniq", "man", "help",
    "where", "which", "dir", "tree", "fc", "comp", "curl", "wget",
    "code", "notepad", "git",
})

_QUOTE_CHARS = "\"'"

# Windows 下抑制子进程控制台窗（Bug B）：getattr 兼容非 Windows 平台导入。
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _segments(command: str) -> list[str]:
    """按 shell 操作符切分命令（&& || | & ; 与裸换行），供逐段检查。"""
    return [seg.strip() for seg in _SEG_SPLIT_RE.split(command) if seg.strip()]


def _tokens(segment: str) -> list[str]:
    """按空白切分但尊重引号——引号内空格不分段（带空格路径是一个 token）。

    P1-6：此前只识别双引号，单引号包裹的带空格路径
    （``'C:\\Program Files\\Python311\\python.exe' a.py``）会在空格处断开，
    basename 变成 ``Program``，python 检测随之失配。单双引号都按翻转处理
    （尽力而为的分词器，不是完整 shell 解析器）。
    """
    out: list[str] = []
    buf: list[str] = []
    in_quote = False
    for ch in segment:
        if ch in _QUOTE_CHARS:
            in_quote = not in_quote
            buf.append(ch)
        elif ch in " \t" and not in_quote:
            if buf:
                out.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


def _strip_quotes(token: str) -> str:
    return token.strip(_QUOTE_CHARS)


def _exe_basename(token: str) -> str:
    """取 token 的可执行名：先剥包裹引号再取 basename、小写、去 .exe。"""
    exe = os.path.basename(_strip_quotes(token)).lower()
    if exe.endswith(".exe"):
        exe = exe[:-4]
    return exe


def _is_python_invocation(segment: str) -> bool:
    """判断一个命令段是否在调用 python/pip。

    覆盖三类绕过形态：
    - 引号包裹的可执行路径（含带空格路径）：token 先剥引号再做 basename
      匹配（加固 ②）；
    - ``call python …`` / ``start "" python …`` / ``cmd /c python …``：
      首个 token 属于 {call, start, cmd, cmd.exe} 时跳过其后以 ``/`` 开头
      的开关参数与一个可能的带引号标题后再检查（加固 ③）；
    - 前导 KEY=VALUE 环境变量赋值照旧跳过。

    边界声明：%VAR% 间接引用（如 ``%PY% x.py``）**不做**静态展开识别——
    需要运行时环境变量才能解析，属于已知盲区，明确不在本函数处理范围。
    无引号文本里的 python 字样（``echo run python now``）可能误报——守卫
    只拒绝执行并提示改用 run_python，无副作用，属可接受残余（P1-6）。
    """
    tokens = _tokens(segment)
    i = 0
    while i < len(tokens) and _ENV_ASSIGN_RE.match(tokens[i]):
        i += 1
    depth = 0
    while i < len(tokens):
        exe = _exe_basename(tokens[i])
        if exe in _PY_INVOKABLE:
            return True
        # 覆盖 python3.12/pythonw 之类写法（但不误伤 ipython 等）
        if exe.startswith("python"):
            return True
        # 注意不能在这里直接 return False：那会让兜底的全 token 扫描永远
        # 执行不到（wsl/python 之类未知包装器正是从这里漏掉的），改为 break
        # 落到 _scan_all_tokens_for_python。
        if exe not in _CMD_PREFIX_TOKENS or depth >= _PREFIX_MAX_DEPTH:
            break
        j = i + 1
        # 跳过以 / 开头的开关参数（cmd /c /d …）
        while j < len(tokens) and tokens[j].startswith("/"):
            j += 1
        if j >= len(tokens):
            return False  # 前缀后没有命令本体（如孤立的 `call`）
        # start "" python：紧跟 start 的带引号参数是窗口标题而非命令。
        # 但 `call "python.exe" -V` 这种引号包住命令本身的形态不能误跳——
        # 标题后的 token 若本身是 python 调用则保留到下一轮循环命中。
        if tokens[j].startswith('"') and j + 1 < len(tokens):
            nxt = _exe_basename(tokens[j])
            if not (nxt in _PY_INVOKABLE or nxt.startswith("python")):
                j += 1
        i = j
        depth += 1
    return _scan_all_tokens_for_python(tokens)


def _scan_all_tokens_for_python(tokens: list[str]) -> bool:
    """P1-6 兜底：**任意位置**出现 python/pip 可执行名都算调用。

    旧实现只在首个可执行位匹配，遇到未知包装器直接 ``return False``——
    ``wsl python a.py`` / ``pwsh -Command python a.py`` / ``conhost python a.py``
    / ``runas /user:x python a.py`` 因此全部漏检。

    误报抑制：一旦本段出现过参数消费型命令（``grep``/``where``/``findstr``,
    其后续 token 是文本/文件而非可执行名），其后的 python 字样一律跳过。
    必须看**整段前缀**而非紧邻前驱——``grep -r python .`` 里 python 的前驱
    是开关 ``-r``，只看紧邻会漏抑制。复合命令经 ``_segments`` 切分后
    ``python x.py`` 独立成段，不受影响。

    残余盲区照旧声明：无引号的 ``echo run python now`` 会误报——守卫只是
    拒绝执行并提示改用 run_python，不产生副作用，可接受。
    """
    saw_consumer = False
    for token in tokens:
        if _exe_basename(token) in _ARG_CONSUMERS:
            saw_consumer = True
            continue
        exe = _exe_basename(token)
        if not saw_consumer and (exe in _PY_INVOKABLE or exe.startswith("python")):
            return True
    return False


def _windows_ansi_codec() -> str | None:
    """Windows ANSI 代码页对应的 Python 编码名；非 Windows 返回 None。

    为什么不用 ``locale.getpreferredencoding(False)``：Python 3.13 在 UTF-8
    模式（或 PYTHONIOENCODING/UTF-8 模式环境）下它返回 ``utf-8``——于是
    「utf-8 失败 → 回退 preferred」的兜底链退化成 utf-8 → utf-8，GBK 字节
    照样解成乱码（实测踩中）。ANSI 代码页必须显式向系统要：中文 Windows
    GetACP()=936 → ``cp936``。``mbcs`` 是 Windows 专有的 ANSI 代码页别名，
    作为 GetACP 不可用时的兜底。
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        acp = int(ctypes.windll.kernel32.GetACP())  # type: ignore[attr-defined]
        if acp > 0:
            return f"cp{acp}"
    except Exception:  # noqa: BLE001 — 编码探测失败不应影响命令执行
        pass
    return "mbcs"


def decode_process_output(data: bytes) -> str:
    """子进程字节流解码：utf-8 strict 失败回退本地 ANSI 代码页（Bug A）。

    中文 Windows 上 cmd.exe 内建命令（dir/echo 等）经管道输出的是
    GBK(cp936) 字节而非 UTF-8——一律按 utf-8+replace 解会得到乱码
    （用户实测「中文路径无法识别」的根因）。

    兜底顺序（取第一个能解的）：
      1. ``utf-8`` strict —— python 子进程 / PYTHONUTF8=1 的输出原样保留；
      2. Windows ANSI 代码页（GetACP → cp936 等；非 Windows 跳过）；
      3. ``locale.getpreferredencoding(False)`` —— POSIX 上的最后参考；
      4. ``utf-8`` + ``errors="replace"`` —— 任何杂凑字节都不抛异常。
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass  # 控制流：非 UTF-8 输出，继续走下方解码兜底链
    candidates: list[str] = []
    ansi = _windows_ansi_codec()
    if ansi:
        candidates.append(ansi)
    candidates.append(locale.getpreferredencoding(False) or "utf-8")
    candidates.append("utf-8")
    for codec in candidates:
        try:
            return data.decode(codec, errors="replace")
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")  # pragma: no cover — 永不可达


async def _kill_process(proc: asyncio.subprocess.Process) -> None:
    """Terminate a subprocess, escalating to kill if necessary."""
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
    except ProcessLookupError:
        pass  # 尽力而为：进程已自行退出，终止目标已达成


async def _run_process(
    args: list[str],
    *,
    cwd: str,
    timeout: int,
    env: dict[str, str] | None = None,
) -> tuple[int, bytes, bytes]:
    """Run a child process with fully awaited pipe cleanup.

    Windows' Proactor subprocess transports can outlive short pytest/app event
    loops even after ``communicate``.  A managed ``Popen`` in a worker thread
    avoids those transports while retaining cancellation/timeout cleanup.

    ``env``：None 表示继承**净化后**的父进程环境（``sanitized_exec_env``，
    A+ 阶段 5 / G-4）；传入完整副本则原样使用（调用方自行负责净化，
    python_exec 传入前已过 ``sanitized_exec_env``）。

    在这里做默认净化而不是各调用方自管，理由是这是**所有模型驱动子进程的
    唯一咽喉**：放调用方意味着每新增一个执行工具都要记得净化，漏一处就是
    密钥泄露面（本次修复正是 bash 漏了——run_python 修了、bash 没修）。
    """
    effective_env = sanitized_exec_env() if env is None else env
    if sys.platform == "win32":
        # Bug B：桌面应用（无控制台窗体）里 spawn cmd.exe 不能闪终端黑框，
        # win32 分支统一加 CREATE_NO_WINDOW（asyncio 分支仅 POSIX 走到）。
        popen_kwargs: dict = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "cwd": cwd,
            "creationflags": _CREATE_NO_WINDOW,
        }
        popen_kwargs["env"] = effective_env
        proc = subprocess.Popen(args, **popen_kwargs)
        try:
            stdout, stderr = await asyncio.to_thread(
                proc.communicate, timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            await asyncio.to_thread(proc.communicate)
            raise asyncio.TimeoutError from exc
        except asyncio.CancelledError:
            proc.kill()
            await asyncio.to_thread(proc.communicate)
            raise
        return proc.returncode, stdout, stderr

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=effective_env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        await _kill_process(proc)
        raise
    return proc.returncode, stdout, stderr


async def run_bash(
    command: str,
    timeout: int = 120,
    cwd: str = ".",
) -> str:
    """Execute a bash command and return stdout + stderr.

    Args:
        command: The shell command to execute.
        timeout: Timeout in seconds.
        cwd: Working directory for the command.
    """
    # R12 P1/A4：冻结态没有独立 Python——python/pip 调用只会把应用 exe
    # 再启动一遍（目标机「目录不存在」弹窗的直接成因）。逐段检查复合命令，
    # 命中即不 spawn、直接给出替代路径指引。
    if getattr(sys, "frozen", False) and any(
        _is_python_invocation(seg) for seg in _segments(command)
    ):
        return _FROZEN_PY_GUARD_MSG

    shell = "/bin/bash"
    if sys.platform == "win32":
        shell = os.environ.get("COMSPEC", "cmd.exe")
        args = [shell, "/c", command]
    else:
        if not os.path.exists(shell):
            shell = "/bin/sh"
        args = [shell, "-c", command]

    try:
        returncode, stdout, stderr = await _run_process(
            args, cwd=cwd, timeout=timeout,
        )
    except asyncio.TimeoutError:
        return f"Error: Command timed out after {timeout} seconds"
    except FileNotFoundError:
        return f"Error: Shell not found: {shell}"
    except Exception as e:
        return f"Error executing command: {e}"

    output_parts = []
    if stdout:
        # Bug A：cmd.exe 内建命令在中文 Windows 输出 GBK——utf-8 strict
        # 失败时回退本地编码，不再一律 replace 成乱码。
        output_parts.append(decode_process_output(stdout))
    if stderr:
        output_parts.append(decode_process_output(stderr))

    result = "\n".join(output_parts).strip()

    if returncode != 0:
        result = f"Exit code: {returncode}\n{result}"

    result = truncate_tool_output(result)

    return result or "(no output)"
