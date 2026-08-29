"""Python code execution tool."""

import asyncio
import sys
import uuid
from pathlib import Path

from ..constants import truncate_tool_output
from .bash import _run_process, decode_process_output
from .exec_provider import sanitized_exec_env


async def run_python(
    code: str,
    timeout: int = 120,
    cwd: str = ".",
    workspace_root: str | None = None,
) -> str:
    """Execute Python code and return stdout + stderr.

    Writes the code to a temporary file in cwd and runs it with the
    current Python interpreter (inheriting venv site-packages).

    冻结版（PyInstaller）没有独立解释器——sys.executable 是应用自身，
    子进程方式会变成「重启整个应用」；改走进程内执行器（frozen_exec），
    使打包进来的 numpy/matplotlib/pandas 真正可用于会话画图与分析。

    Args:
        code: Python source code to execute.
        timeout: Timeout in seconds.
        cwd: Working directory for execution.
        workspace_root: 工作区根绝对路径（冻结分支注入 WS 常量用；
            开发态忽略）。
    """
    if getattr(sys, "frozen", False):
        from .frozen_exec import run_python_inprocess

        return await run_python_inprocess(
            code, timeout=timeout, cwd=cwd, workspace_root=workspace_root,
        )

    temp_name = f"_ra_exec_{uuid.uuid4().hex[:8]}.py"
    temp_path = Path(cwd) / temp_name

    try:
        temp_path.write_text(code, encoding="utf-8")
    except Exception as e:
        return f"Error writing temp file: {e}"

    try:
        # Bug A 源头治理：给 python 子进程注入 PYTHONUTF8=1（完整环境副本），
        # 让子进程的 print/文件读写默认 utf-8，减少乱码产生面；输出侧仍有
        # decode_process_output 兜底链双保险。
        # A+ 阶段 5 / G-4：剔除疑似密钥后再交给模型代码（原为完整 os.environ，
        # 模型一行 os.environ["LLM_API_KEY"] 即可读走全部密钥）。
        child_env = {**sanitized_exec_env(), "PYTHONUTF8": "1"}
        returncode, stdout, stderr = await _run_process(
            [sys.executable, str(temp_path)], cwd=cwd, timeout=timeout,
            env=child_env,
        )
    except asyncio.TimeoutError:
        return f"Error: Python code timed out after {timeout} seconds"
    except FileNotFoundError:
        return f"Error: Python interpreter not found: {sys.executable}"
    except Exception as e:
        return f"Error executing Python code: {e}"
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass  # 尽力而为：临时脚本清理失败不影响执行结果返回

    output_parts = []
    if stdout:
        # Bug A：与 bash 同一解码兜底链（utf-8 strict → 本地编码 replace）
        output_parts.append(decode_process_output(stdout))
    if stderr:
        output_parts.append(decode_process_output(stderr))

    result = "\n".join(output_parts).strip()

    if returncode != 0:
        result = f"Exit code: {returncode}\n{result}"

    result = truncate_tool_output(result)

    return result or "(no output)"
