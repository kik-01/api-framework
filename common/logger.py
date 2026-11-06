"""日志封装。

不使用 print：无法分级、无法关闭、无法落盘。
本模块支持 debug / info 两级，同时输出到控制台与文件，便于回溯。

两条工程约定：
  1. 文件日志使用 RotatingFileHandler 轮转，避免长期跑把磁盘写满。
  2. 输出请求 / 响应前先过 mask_sensitive：
     当前被测对象是公开 mock 数据，风险低；但同一套框架接到真实业务后，
     token、手机号、密码会直接写进日志文件，属于典型的敏感信息泄露。
"""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler

from common.settings import LOG_DIR

_CONFIGURED: set[str] = set()

# 这些字段名一旦出现在日志里，值统一打码
SENSITIVE_KEYS = frozenset(
    {"password", "passwd", "pwd", "token", "authorization", "cookie",
     "secret", "access_token", "refresh_token", "phone", "mobile", "id_card"}
)

# 响应体是字符串，按 JSON 键值对打码
_TEXT_PATTERN = re.compile(
    r'("(?:' + "|".join(SENSITIVE_KEYS) + r')"\s*:\s*)"[^"]*"',
    re.IGNORECASE,
)


def mask_sensitive(payload):
    """把请求参数 / 响应体里的敏感字段打码，其余原样返回。

    dict / list 递归处理；字符串按 key: value 模式替换。
    打码只影响日志输出，不影响实际发出的请求。
    """
    if isinstance(payload, dict):
        return {
            k: ("***" if str(k).lower() in SENSITIVE_KEYS else mask_sensitive(v))
            for k, v in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [mask_sensitive(item) for item in payload]
    if isinstance(payload, str):
        return _TEXT_PATTERN.sub(r'\1"***"', payload)
    return payload


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

    # 文件：全量记录，出问题回查；单文件 2MB × 3 份，避免无限增长
    file_handler = RotatingFileHandler(
        LOG_DIR / "run.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    logger.propagate = False
    _CONFIGURED.add(name)
    return logger
