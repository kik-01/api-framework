"""日志封装。

设计取舍：为什么不用 print？
- print 没法分级（debug/info/error），出问题时分不清主次
- print 没法关（CI 上跑几万条用例会刷屏）
- print 没法同时输出到文件，出问题时没有历史可查
"""

from __future__ import annotations

import logging
import sys

from common.settings import LOG_DIR

_CONFIGURED: set[str] = set()


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if name in _CONFIGURED:
        return logger

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # 控制台：只看 info 以上，跑用例时不刷屏
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # 文件：全量记录，出问题回查
    file_handler = logging.FileHandler(LOG_DIR / "run.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    logger.propagate = False
    _CONFIGURED.add(name)
    return logger
