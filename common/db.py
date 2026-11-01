"""数据库访问封装，用于校验「接口返回成功」与「数据实际落库」是否一致。

HTTP 200/201 只代表服务端处理完请求，不代表数据已写入数据库。
常见的不一致来源：异步写入的延迟、事务回滚后响应已发出、主从复制延迟。
接口测试需补充查库对账：用返回的 id 查询记录并比对字段值。

使用 sqlite3 而非 pymysql：被测服务为本地 mock，SQLite 免安装、免密码，CI 可直接运行。
上层接口（query_one / count）与连接方式解耦，切换 pymysql 只需替换 connect 部分。
返回 dict 而非 Row：按字段名取值，新增字段不会导致错位。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from common.logger import get_logger
from common.settings import CONFIG, ROOT

log = get_logger(__name__)


def _db_path() -> Path:
    """从配置里取数据库文件路径，相对路径按项目根目录解析。"""
    db_cfg = CONFIG.get("database") or {}
    raw = db_cfg.get("path", "data/test.db")
    path = Path(raw)
    return path if path.is_absolute() else (ROOT / path)


class Db:
    """极简数据库客户端，只提供测试需要的几个方法。"""

    def __init__(self, path: str | Path | None = None):
        self.path = str(path or _db_path())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    # ---------- 内部 ----------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row      # 让结果能按列名取：row["name"]
        return conn

    # ---------- 对外 ----------

    def query_one(self, sql: str, params: tuple = ()) -> dict | None:
        """查一条，返回 dict；查不到返回 None。"""
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row is not None else None

    def query_all(self, sql: str, params: tuple = ()) -> list[dict]:
        """查多条，返回 dict 列表。"""
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def count(self, table: str, where: str = "1=1", params: tuple = ()) -> int:
        """count 一行，用来断言「到底有没有写进去」。"""
        row = self.query_one(f"SELECT COUNT(*) AS c FROM {table} WHERE {where}", params)
        return int(row["c"]) if row else 0

    def execute(self, sql: str, params: tuple = ()) -> None:
        """执行写操作（测试里一般只用来清数据）。"""
        with self._connect() as conn:
            conn.execute(sql, params)

    def truncate(self, table: str) -> None:
        """清空一张表，用于用例之间的数据隔离。"""
        with self._connect() as conn:
            conn.execute(f"DELETE FROM {table}")

    def ping(self) -> bool:
        """连通性检查，配置里 enabled=false 时可以跳过校验。"""
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception as exc:               # noqa: BLE001
            log.warning("数据库连接失败: %s", exc)
            return False
