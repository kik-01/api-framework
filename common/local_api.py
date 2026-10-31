"""本地被测服务 —— 一个真正会写数据库的极简用户 API。

为什么需要自己起一个服务（而不是继续用 jsonplaceholder）：

    jsonplaceholder 是 mock 服务，POST 只返回一个假 id，**不会真的落库**。
    所以「创建后查询」必然 404，没法验证「接口返回成功 → 数据真的进库了」这条链路。
    为了把这个短板补上，这里用标准库起一个真实会写 SQLite 的服务。

被测接口：
    POST /users          创建用户，写库，返回 201 + {id, name, city}
    GET  /users/{id}     查用户，读库，200 或 404
    POST /users/broken   故意「假成功」：返回 200 但不写库
                         —— 专门用来证明「查库校验」能发现 200 的假象

为什么用标准库 http.server 而不是 Flask/FastAPI：
    不想为测试框架的辅助服务多装一层依赖，也不想让 CI 多一步。
    80 行标准库够用，不必为此引入 Web 框架依赖。
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
