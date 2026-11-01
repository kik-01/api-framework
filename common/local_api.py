"""本地被测服务：一个会真实写入 SQLite 的极简用户 API。

mock 服务不落库，POST 返回的 id 无法查询，因此无法验证
「接口返回成功」到「数据真正入库」这条链路。本服务实现同一组接口，但会真实写库。

接口：
    POST /users          创建用户，写入 SQLite，返回 201 与 {id, name, city}
    GET  /users/{id}     查询用户，200 或 404
    POST /users/broken   返回 200 但不写库，用于验证查库校验能识别假成功

使用 http.server 而非 Flask/FastAPI：辅助服务不引入额外依赖，CI 也无需多一步安装。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    city TEXT NOT NULL
);
"""


class _Handler(BaseHTTPRequestHandler):
    db_path: str = ""
    server_version = "LocalQA/1.0"

    # ---------- 工具 ----------

    def log_message(self, *args):        # 静音，避免污染 pytest 输出
        pass

    def _send(self, code: int, payload: dict | None = None) -> None:
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ---------- 路由 ----------

    def do_POST(self):                                    # noqa: N802
        if self.path == "/users":
            body = self._read_json()
            name, city = body.get("name", ""), body.get("city", "")
            if not name or not city:
                return self._send(400, {"error": "name 和 city 必填"})
            with self._connect() as conn:
                cur = conn.execute("INSERT INTO users(name, city) VALUES(?, ?)", (name, city))
                uid = cur.lastrowid
            return self._send(201, {"id": uid, "name": name, "city": city})

        if self.path == "/users/broken":
            # 故意不写库 —— 用来演示「接口返回 200，但数据没落库」
            body = self._read_json()
            return self._send(200, {"id": 999, "name": body.get("name"), "city": body.get("city")})

        return self._send(404, {"error": "not found"})

    def do_GET(self):                                     # noqa: N802
        if self.path.startswith("/users/"):
            raw = self.path.split("/")[-1]
            if not raw.isdigit():
                return self._send(400, {"error": "id 必须是数字"})
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM users WHERE id = ?", (int(raw),)).fetchone()
            if row is None:
                return self._send(404, {"error": "用户不存在"})
            return self._send(200, dict(row))
        return self._send(404, {"error": "not found"})


def start(db_path: str | Path) -> tuple[ThreadingHTTPServer, str]:
    """启动服务，返回 (server, base_url)。

    端口用 0 让系统分配，避免与本机已占用的端口冲突。
    调用方负责在结束时 server.shutdown()。
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)

    _Handler.db_path = str(db_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
