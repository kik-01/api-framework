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
    """读取当前环境的配置文件。

    settings 在**导入时**就会执行本函数，所以配置缺失时必须给出能直接照做的报错；
    否则异常会伪装成 `ImportError while loading conftest`，让人误以为是代码问题。
    """
    if not CONFIG_FILE.exists():
        env_root = ROOT / "config"
        available = sorted(p.parent.name for p in env_root.glob("*/config.yaml"))
        raise SystemExit(
            "\n[配置错误] 找不到配置文件：%s\n"
            "  当前 TEST_ENV=%r\n"
            "  可用环境：%s\n"
            "  解决：set TEST_ENV=test（或删除这个环境变量）\n"
            % (CONFIG_FILE, ENV, "、".join(available) or "（无）")
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
