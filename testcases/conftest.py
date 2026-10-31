"""pytest 全局 fixture。

设计说明：
- 为什么用 fixture 而不是模块级全局变量？
  → fixture 有明确的作用域（function/class/module/session），
    能保证每个用例拿到干净的数据；全局变量会被上一个用例污染，
    产生"单独跑能过、一起跑就挂"的经典问题。
- 为什么 yield 而不是 return？
  → yield 可以做前置+后置（setup/teardown），比如下面 client 用完关闭 session。
"""

from __future__ import annotations

import pytest

from common.api_client import ApiClient
from common.logger import get_logger
from common.settings import CONFIG, DATA_DIR, load_yaml

log = get_logger(__name__)


@pytest.fixture(scope="session")
def client() -> ApiClient:
    """整个测试会话共用一个 HTTP 客户端（复用连接，快很多）。"""
    log.info("初始化 ApiClient -> %s", CONFIG["base_url"])
    api = ApiClient()
    yield api
    api.session.close()
    log.info("测试会话结束，连接已关闭")


@pytest.fixture(scope="session")
def post_data() -> dict:
    """加载岗位测试数据（只读一次）。"""
    return load_yaml("post_data.yaml")


@pytest.fixture
def created_post(client: ApiClient) -> dict:
    """创建一个资源，用完删掉。

    这是"接口依赖链"的标准处理方式：
      创建 -> 用例用 -> 清理
    如果没有清理，反复跑会在环境里堆垃圾数据，
    最终导致"第 100 次跑挂了"——这是接口自动化最常见的腐化方式。
    """
    resp = client.post(
        "/posts",
        json_body={"title": "fixture-temp", "body": "temporary", "userId": 1},
    )
    assert resp.status_code == 201, f"fixture 创建资源失败: {resp.status_code}"
    resource = resp.json()
    log.debug("fixture 创建资源 id=%s", resource.get("id"))

    yield resource

    # 后置清理。jsonplaceholder 是 mock 服务不会真删，
    # 真实项目这里必须真的调删除接口，否则环境会被污染。
    del_resp = client.delete(f"/posts/{resource.get('id')}")
    log.debug("fixture 清理资源 id=%s -> %s", resource.get("id"), del_resp.status_code)


# ============================================================
# 落库一致性校验用的本地服务
# ============================================================

@pytest.fixture(scope="session")
def local_api() -> dict:
    """启动一个真正会写 SQLite 的本地服务，供「接口 + 落库」校验使用。

    为什么不用 jsonplaceholder：
        它是 mock 服务，POST 只返回假 id，不落库 —— 没法验证「接口说成功，数据到底进没进库」。
        这个 fixture 用标准库起一个 127.0.0.1 的极简用户 API，真实写库。

    为什么 scope="session"：
        整个会话只起一次，避免每条用例反复建表、反复绑定端口，跑得快。

    为什么端口用 0：
        让系统分配空闲端口，避免与本机已占用端口冲突。
    """
    from common.db import Db
    from common.local_api import start

    db_path = DATA_DIR / "test.db"
    if db_path.exists():
        db_path.unlink()

    server, base_url = start(db_path)
    api = ApiClient(base_url=base_url, timeout=5)
    db = Db(db_path)
    log.info("本地被测服务已启动: %s（库: %s）", base_url, db_path)

    yield {"client": api, "db": db, "base_url": base_url}

    api.session.close()
    server.shutdown()
    log.info("本地被测服务已关闭")
