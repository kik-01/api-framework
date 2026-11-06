# -*- coding: utf-8 -*-
"""环境自检：一条命令查完 Python 版本、依赖、配置、网络与目录。

用法：
    py check_env.py

退出码 0 = 全部通过，可以直接跑 pytest；1 = 有未通过项，按提示处理。
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS: list[tuple[str, bool, str, str]] = []


def add(name: str, ok: bool, detail: str, fix: str = "") -> None:
    RESULTS.append((name, ok, detail, fix))


# ---------- 1. Python 版本 ----------
version = sys.version.split()[0]
add(
    "Python 版本",
    sys.version_info >= (3, 10),
    "%s（%s）" % (version, sys.executable),
    "需要 3.10+（代码用了 str | None 写法）",
)

# ---------- 2. 依赖 ----------
for mod, pkg in [
    ("pytest", "pytest"),
    ("requests", "requests"),
    ("yaml", "PyYAML"),
    ("allure_pytest", "allure-pytest"),
]:
    found = importlib.util.find_spec(mod) is not None
    add(
        "依赖 " + pkg,
        found,
        "已安装" if found else "缺失",
        "%s -m pip install -r requirements.txt" % Path(sys.executable).name,
    )

# ---------- 3. 配置 ----------
env = os.environ.get("TEST_ENV", "test")
cfg = ROOT / "config" / env / "config.yaml"
add(
    "配置文件",
    cfg.exists(),
    "TEST_ENV=%s → %s" % (env, cfg.relative_to(ROOT)),
    "检查 TEST_ENV 是否指向了不存在的环境；或从 config/test 复制一份",
)

# ---------- 4. 网络（尽量用配置里的 base_url）----------
base = "https://jsonplaceholder.typicode.com"
timeout_s = 30
if cfg.exists():
    try:
        import yaml

        with cfg.open(encoding="utf-8") as fh:
            conf = yaml.safe_load(fh) or {}
        base = conf.get("base_url", base)
        timeout_s = conf.get("timeout", timeout_s)
    except Exception:  # noqa: BLE001
        pass

start = time.time()
try:
    with urllib.request.urlopen(base + "/posts/1", timeout=15) as resp:
        cost = int((time.time() - start) * 1000)
        add(
            "网络连通",
            resp.status == 200,
            "%s  %s  %sms" % (base, resp.status, cost),
            "检查代理 / VPN；或调大 config.yaml 的 timeout（当前 %ss）" % timeout_s,
        )
except Exception as exc:  # noqa: BLE001
    add(
        "网络连通",
        False,
        "%s  %s" % (base, type(exc).__name__),
        "检查网络与代理；离线时只跑落库用例：py -m pytest testcases/test_db_consistency.py",
    )

# ---------- 5. 目录 ----------
for d, optional in [("logs", False), ("data", False), ("reports", True)]:
    p = ROOT / d
    add(
        "目录 %s/" % d,
        p.is_dir() or optional,
        "存在" if p.is_dir() else ("可缺省，首次运行会自动建" if optional else "将被自动创建"),
    )

# ---------- 输出 ----------
print("\n环境自检 —— %s\n" % ROOT)
for name, ok, detail, fix in RESULTS:
    print("%s %-14s %s" % ("[ OK ]" if ok else "[FAIL]", name, detail))
    if not ok and fix:
        print("         └ 解决：%s" % fix)

failed = sum(1 for _, ok, _, _ in RESULTS if not ok)
print()
if failed:
    print("%d 项未通过，按上面的「解决」处理后再跑。" % failed)
else:
    print("全部通过，可以跑测试了：py -m pytest")
print()
sys.exit(1 if failed else 0)
