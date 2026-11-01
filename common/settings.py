"""全局配置与路径管理。

配置从 YAML 读取，切换测试环境无需改动代码。
路径使用 pathlib，兼容 Windows 与 Linux 的分隔符差异。
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

# 项目根目录（本文件在 common/ 下，所以上一级）
ROOT = Path(__file__).resolve().parent.parent

# 用环境变量切换环境，默认 test。CI 上可以 export TEST_ENV=staging
ENV = os.environ.get("TEST_ENV", "test")

CONFIG_FILE = ROOT / "config" / ENV / "config.yaml"
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
LOG_DIR = ROOT / "logs"


def load_config() -> dict:
    """读取当前环境的配置文件。"""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"找不到配置文件: {CONFIG_FILE}\n"
            f"请确认 config/{ENV}/config.yaml 存在，或用 TEST_ENV 指定环境。"
        )
    with CONFIG_FILE.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


CONFIG = load_config()


def load_yaml(relative_path: str) -> dict | list:
    """读取 data/ 下的 YAML 测试数据文件。

    用法：load_yaml("post_data.yaml")
    """
    path = DATA_DIR / relative_path
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)
