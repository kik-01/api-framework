"""pytest 全局 fixture。

使用 fixture 而非模块级全局变量：fixture 有明确作用域（function / class / module / session），
保证每条用例拿到干净的数据，避免「单独跑通过、一起跑失败」的用例间污染。
使用 yield 而非 return，以便在用例结束后执行清理（如关闭 session）。
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


def pytest_generate_tests(metafunc):
    """把 YAML 里的测试数据注入用例参数，新增用例只需加数据行。

    case     -> valid_posts    正常创建场景
    bad_case -> invalid_posts  异常参数场景
    post_id  -> valid_ids      查询场景
    """
    if "case" in metafunc.fixturenames:
        cases = load_yaml("post_data.yaml")["valid_posts"]
        metafunc.parametrize("case", cases, ids=[c["case_id"] for c in cases])
    if "bad_case" in metafunc.fixturenames:
        bad_cases = load_yaml("post_data.yaml")["invalid_posts"]
        metafunc.parametrize("bad_case", bad_cases, ids=[c["case_id"] for c in bad_cases])
    if "post_id" in metafunc.fixturenames:
        id_list = load_yaml("post_data.yaml")["valid_ids"]
        metafunc.parametrize("post_id", id_list, ids=[str(i) for i in id_list])


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
    #
    # 清理失败不能影响用例结论：teardown 抛异常时，pytest 会把**本已通过**的用例
    # 记成 ERROR，报告里就分不清「业务断言失败」和「清理失败」。
    # 因此这里只记警告，删除契约是否成立由专门的用例去断言。
    try:
        del_resp = client.delete(f"/posts/{resource.get('id')}")
        log.debug("fixture 清理资源 id=%s -> %s", resource.get("id"), del_resp.status_code)
    except Exception as exc:                       # noqa: BLE001
        log.warning(
            "fixture 清理资源 id=%s 失败（不影响用例结论）: %s",
            resource.get("id"), exc,
        )


# ============================================================
# 落库一致性校验用的本地服务
# ============================================================

@pytest.fixture(scope="session")
def local_api() -> dict:
    """启动会写 SQLite 的本地服务，供「接口 + 落库」校验使用。

scope="session"：整个会话只启动一次，避免每条用例重复建表与绑定端口。
端口设为 0：由系统分配空闲端口，避免与本机已占用端口冲突。
config.yaml 的 database.enabled=false 时跳过整组落库用例。
    """
    from common.db import Db
    from common.local_api import start

    db_cfg = CONFIG.get("database") or {}
    if not db_cfg.get("enabled", True):
        pytest.skip("config.yaml 中 database.enabled=false，跳过落库一致性用例")

    db_path = DATA_DIR / "test.db"
    # Windows 下连接未释放会锁文件；连 WAL 的附属文件一起清
    for suffix in ("", "-wal", "-shm"):
        leftover = db_path.with_name(db_path.name + suffix)
        if leftover.exists():
            try:
                leftover.unlink()
            except OSError as exc:                   # noqa: PERF203
                log.warning("旧库文件清理失败 %s: %s", leftover, exc)

    server, base_url = start(db_path)
    api = ApiClient(base_url=base_url, timeout=5)
    db = Db(db_path)
    log.info("本地被测服务已启动: %s（库: %s）", base_url, db_path)

    yield {"client": api, "db": db, "base_url": base_url}

    api.session.close()
    server.shutdown()          # 停止 serve_forever 循环
    server.server_close()      # 释放监听端口，避免重复运行时地址被占用
    log.info("本地被测服务已关闭")
