"""防回归锁：「试用到期炸弹」不得在 launcher_restricted 中复活。

历史上 research_assistant/launcher_restricted.py 内置了一个日期门禁：
到达某个硬编码日期后弹窗提示并 sys.exit(1) 拒绝启动，未到期也会打印
剩余天数。该逻辑已于 2026-08 被彻底移除，模块退化为纯粹的启动委托。
本测试把这个契约 pin 死——未来任何改动若把日期门禁加回来，这里必须
立刻变红。

两层防线：
  1. 运行时断言：模块不得暴露门禁属性/函数；
  2. 源码文本扫描：门禁特征串一律禁入（能挡住换名复活的变体）。

注意：测试只 import/加载模块并读源码文本，绝不触发 __main__ 分支，
因此不会真正启动应用。
"""

import importlib.util
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "research_assistant"
    / "launcher_restricted.py"
)

# 到期门禁的特征串：出现任何一条都意味着炸弹（或其变体）回来了
BANNED_MARKERS = (
    "EXPIRE_DATE",
    "check_expiry",
    "date.today",
    "messagebox",
    "sys.exit",
)


def _load_module():
    """按文件路径加载 launcher_restricted（不触发其 __main__ 块）。"""
    spec = importlib.util.spec_from_file_location(
        "launcher_restricted_under_test", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_expire_gate_attributes():
    """运行时层：门禁属性不得存在；同名函数若被保留必须是无副作用空操作。"""
    mod = _load_module()
    assert not hasattr(mod, "EXPIRE_DATE"), (
        "launcher_restricted 再次暴露了到期日期常量 —— 到期炸弹不得复活"
    )
    if hasattr(mod, "check_expiry"):  # 允许存在无副作用的兼容占位，但仅限于此
        try:
            result = mod.check_expiry()
        except SystemExit as exc:
            raise AssertionError(
                "check_expiry 触发了进程退出 —— 到期门禁复活，拒绝通过"
            ) from exc
        assert result is None, "check_expiry 必须是无副作用、立即返回的占位"


def test_source_contains_no_gate_markers():
    """源码层：门禁特征串一律禁入（比属性断言更能挡住改名复活的变体）。"""
    source = MODULE_PATH.read_text(encoding="utf-8")
    for marker in BANNED_MARKERS:
        assert marker not in source, (
            f"launcher_restricted 源码中出现到期门禁特征串 {marker!r} —— "
            "到期炸弹不得复活"
        )


def test_still_delegates_to_launcher_main():
    """入口契约：__main__ 分支仍需委托 research_assistant.launcher.main()，
    保证 build.py --restricted 以本文件为 entry 时应用照常可启动。"""
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in source
    assert "from research_assistant.launcher import main" in source
