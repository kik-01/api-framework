"""本地被测服务：一个会真实写入 SQLite 的极简用户 API。

mock 服务不落库，POST 返回的 id 无法查询，因此无法验证
「接口返回成功」到「数据真正入库」这条链路。本服务实现同一组接口，但会真实写库。

接口：
    POST /users          创建用户，写入 SQLite，返回 201 与 {id, name, city}
    GET  /users/{id}     查询用户，200 或 404
    POST /users/broken   返回 200 但不写库，用于验证查库校验能识别假成功

使用 http.server 而非 Flask/FastAPI：辅助服务不引入额外依赖，CI 也无需多一步安装。

作为被测服务，它本身也要经得起边界情况：
  · 路径先剥离 query string，避免 /users/1?x=1 被当成 id "1?x=1"；
  · 畸形 JSON 返回 400，而不是抛异常断开连接；
  · 请求体设长度上限，避免一个超大 body 把内存吃满；
  · 连接显式关闭，并开启 WAL，减少多线程下的 database is locked。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

MAX_BODY_BYTES = 1 * 1024 * 1024        # 1MB，超过直接 413

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

    @property
    def route(self) -> str:
        """只取路径部分：/users/1?x=1 -> /users/1。"""
        return urlsplit(self.path).path

    def _send(self, code: int, payload: dict | None = None) -> None:
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _read_json(self) -> dict:
        """读取并解析 JSON 请求体，非法输入抛 ValueError 由调用方转成 400。"""
        raw_length = self.headers.get("Content-Length") or 0
        try:
            length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise ValueError("Content-Length 必须是整数") from exc

        if not length:
            return {}
        if length > MAX_BODY_BYTES:
            raise ValueError(f"请求体超过 {MAX_BODY_BYTES} 字节上限")

        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求体不是合法 JSON") from exc

        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ---------- 路由 ----------

    def do_POST(self):                                    # noqa: N802
        route = self.route

        if route == "/users":
            try:
                body = self._read_json()
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})

            name, city = body.get("name", ""), body.get("city", "")
            if not name or not city:
                return self._send(400, {"error": "name 和 city 必填"})

            with closing(self._connect()) as conn:
                cur = conn.execute("INSERT INTO users(name, city) VALUES(?, ?)", (name, city))
                uid = cur.lastrowid
                conn.commit()
            return self._send(201, {"id": uid, "name": name, "city": city})

        if route == "/users/broken":
            # 故意不写库 —— 用来演示「接口返回 200，但数据没落库」
            try:
                body = self._read_json()
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
            return self._send(200, {"id": 999, "name": body.get("name"), "city": body.get("city")})

        return self._send(404, {"error": "not found"})

    def do_GET(self):                                     # noqa: N802
        route = self.route
        if route.startswith("/users/"):
            raw = route.split("/")[-1]
            if not raw.isdigit():
                return self._send(400, {"error": "id 必须是数字"})
            with closing(self._connect()) as conn:
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
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode=WAL")     # 读写并发时少踩 database is locked
        conn.commit()

    _Handler.db_path = str(db_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
