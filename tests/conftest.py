"""共享 fixtures。

appdata 隔离（R8）：config.app_data_dir / ensure_global_config 会读写
真实 %APPDATA%（Windows）或 ~/.research-assistant（其它平台）。凡涉及
全局配置的测试必须挂 ``isolated_appdata``，避免污染（或读取）用户真实
配置。
"""

import os
from pathlib import Path

import pytest


@pytest.fixture()
def isolated_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把「应用数据目录」重定向到 tmp_path/RA_APPDATA。"""
    fake = tmp_path / "RA_APPDATA"
    fake.mkdir()
    if os.name == "nt":
        monkeypatch.setenv("APPDATA", str(fake))
    else:
        monkeypatch.setenv("HOME", str(fake))
    return fake
