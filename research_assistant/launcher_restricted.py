"""Restricted launcher — thin delegate kept as a legacy packaging entry.

历史版本曾内置三个月试用到期门禁（到期即弹窗并退出进程、未到期则打印剩余
天数），已于 2026-08 彻底移除。build.py --restricted 仍以本文件作为打包
entry（产出 ResearchAssistant_Trial.exe），故保留此薄委托壳：本模块不再做
任何门禁检查，仅在作为脚本执行时转发到 research_assistant.launcher.main()。

防回归锁见 tests/test_launcher_restricted.py。
"""

if __name__ == "__main__":
    from research_assistant.launcher import main

    main()
