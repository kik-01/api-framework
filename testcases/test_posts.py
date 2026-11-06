"""职位资源（/posts）接口测试。

被测服务：https://jsonplaceholder.typicode.com  （公开 mock API，无需注册）

覆盖维度：
  1. 正常场景  —— 查询、创建、更新、删除
  2. 参数化    —— 一批数据跑同一条用例
  3. 异常场景  —— 非法 ID、不存在资源、错误方法、边界值
  4. 结构校验  —— 响应字段类型
  5. 性能基线  —— 响应时间
  6. 接口依赖  —— 创建后查询（fixture 维护生命周期）

说明：
  jsonplaceholder 是 mock 服务 —— 它**总是**返回 200/201，
  不会真的校验参数、也不会真的删除数据。
  所以"异常参数返回 400"这类断言在这里会失败，这是**预期行为**，
  相关用例我用 pytest.mark.xfail 标记了，用来演示"框架能发现接口不符合契约"。
  指向真实接口时，去掉 xfail 即可。
"""

from __future__ import annotations

import pytest

from common.api_client import ApiClient
from common.validators import (
    assert_fields,
    assert_json_key,
    assert_response_time,
    assert_schema,
    assert_status,
)


# ============================================================
# 一、正常场景
# ============================================================

class TestPostsQuery:
    """查询类接口。"""

    def test_get_post_list(self, client: ApiClient):
        """获取列表：校验状态码、返回类型与非空。

        必须带 _limit：不带时该接口一次返回 100 条完整记录，
        公网延迟下容易触发 ReadTimeout。回归测试不应对无上限的列表接口发请求，
        真实项目的列表接口由前端分页，测试同样需要分页参数。
        """
        resp = client.get("/posts", params={"_limit": 10})
        assert_status(resp, 200, "获取文章列表")
        body = resp.json()
        assert isinstance(body, list), "列表接口应返回数组"
        assert len(body) > 0, "列表不应为空"
        assert len(body) <= 10, f"_limit=10 应生效，实际返回 {len(body)} 条"

    def test_get_single_post(self, client: ApiClient):
        """获取单条：字段齐全且值正确。"""
        resp = client.get("/posts/1")
        assert_status(resp, 200, "获取 id=1 的文章")
        assert_fields(resp, {"id": 1, "userId": 1}, "字段值断言")

    def test_get_post_schema(self, client: ApiClient, post_data: dict):
        """结构校验：字段名与类型都符合约定。"""
        resp = client.get("/posts/1")
        assert_status(resp, 200)
        assert_schema(resp, post_data["post_schema"], "文章结构校验")

    def test_query_with_params(self, client: ApiClient):
        """带查询参数：只返回匹配 userId 的数据。"""
        resp = client.get("/posts", params={"userId": 1, "_limit": 20})
        assert_status(resp, 200, "按 userId 过滤")
        body = resp.json()
        assert len(body) > 0, "userId=1 应有数据"
        wrong = [item for item in body if item.get("userId") != 1]
        assert not wrong, f"过滤失效，返回了 userId!=1 的数据: {wrong[:2]}"


class TestPostsWrite:
    """写入类接口（增删改）。"""

    def test_create_post(self, client: ApiClient):
        """创建：应返回 201 且回显数据。"""
        payload = {"title": "新文章", "body": "内容", "userId": 1}
        resp = client.post("/posts", json_body=payload)
        assert_status(resp, 201, "创建文章")
        assert_fields(resp, payload, "创建后应回显提交的数据")
        assert_json_key(resp, "id", "创建后应返回新资源 id")

    def test_update_post_put(self, client: ApiClient):
        """PUT 全量更新。"""
        payload = {"id": 1, "title": "更新后的标题", "body": "更新后的内容", "userId": 1}
        resp = client.put("/posts/1", json_body=payload)
        assert_status(resp, 200, "PUT 更新")
        assert_fields(resp, {"title": "更新后的标题"}, "更新后标题应变化")

    def test_update_post_patch(self, client: ApiClient):
        """PATCH 局部更新：只改一个字段，其他字段不受影响。

        PUT 与 PATCH 的区别：
          PUT   —— 全量替换，没传的字段会被清空
          PATCH —— 局部更新，只改传了的字段
        """
        resp = client.patch("/posts/1", json_body={"title": "只改标题"})
        assert_status(resp, 200, "PATCH 局部更新")
        assert_fields(resp, {"title": "只改标题"}, "标题应被修改")

    def test_delete_post(self, client: ApiClient):
        """删除：成功通常返回 200 或 204。"""
        resp = client.delete("/posts/1")
        assert resp.status_code in (200, 204), (
            f"删除应返回 200/204，实际 {resp.status_code}"
        )


# ============================================================
# 二、参数化（一份数据跑一条用例）
# ============================================================

class TestPostsParametrized:
    """用 pytest.mark.parametrize 展开数据驱动用例。"""

    def test_create_with_various_data(self, client: ApiClient, case: dict):
        """同一逻辑、不同数据；数据来自 data/post_data.yaml 的 valid_posts。"""
        resp = client.post(
            "/posts",
            json_body={
                "title": case["title"],
                "body": case["body"],
                "userId": case["userId"],
            },
        )
        assert_status(resp, 201, f'创建文章 {case["case_id"]}')
        assert_fields(resp, {"title": case["title"]}, "标题应原样回显")

    def test_get_various_ids(self, client: ApiClient, post_id: int):
        """批量验证不同 id 都能取到；id 集合来自 YAML 的 valid_ids。"""
        resp = client.get(f"/posts/{post_id}")
        assert_status(resp, 200, f"获取 id={post_id}")
        assert_fields(resp, {"id": post_id}, "返回的 id 应与请求一致")


# ============================================================
# 三、异常场景
# ============================================================

class TestPostsNegative:
    """异常场景 —— 测试的价值一半在这里。"""

    def test_get_nonexistent_post(self, client: ApiClient):
        """请求不存在的资源：应返回 404。

        这是**真实生效**的异常用例（不是 xfail），
        因为 jsonplaceholder 对不存在的 id 确实返回 404。
        """
        resp = client.get("/posts/999999")
        assert_status(resp, 404, "不存在的资源应返回 404")

    def test_invalid_id_format(self, client: ApiClient):
        """非法 id 格式（字符串）：应返回 4xx，不应 500。

        重点：**不能返回 500**。服务端 500 意味着未处理的异常，
        这是要报 bug 的。
        """
        resp = client.get("/posts/abc")
        assert resp.status_code != 500, "非法参数不应导致服务端 500"
        assert 400 <= resp.status_code < 500, (
            f"非法参数应返回 4xx，实际 {resp.status_code}"
        )

    def test_wrong_method(self, client: ApiClient):
        """错误的方法：对只支持读写的资源用 DELETE 列表。"""
        resp = client.delete("/posts")
        assert resp.status_code != 500, "方法不支持不应导致 500"

    @pytest.mark.xfail(
        reason="jsonplaceholder 不校验参数，缺失或类型错误仍返回 201；"
               "接真实接口后应返回 400/422。",
        strict=False,
    )
    def test_create_with_invalid_payload(self, client: ApiClient, bad_case: dict):
        """异常参数：缺少必填字段或类型错误，应返回 400/422。"""
        resp = client.post("/posts", json_body=bad_case["payload"])
        assert resp.status_code in bad_case["expect_status"], (
            f'{bad_case["case_id"]} 应返回 {bad_case["expect_status"]}，'
            f"实际 {resp.status_code}"
        )


# ============================================================
# 四、性能基线
# ============================================================

class TestPostsPerformance:

    def test_response_time(self, client: ApiClient, post_data: dict):
        """响应时间不应超过基线。"""
        resp = client.get("/posts/1")
        assert_status(resp, 200)
        assert_response_time(
            resp, post_data["perf"]["max_response_ms"], "单条查询响应时间"
        )


# ============================================================
# 五、接口依赖链（创建 -> 使用 -> 清理）
# ============================================================

class TestPostsDependencyChain:
    """验证接口依赖链：创建 → 使用 → 清理。

    jsonplaceholder 不持久化数据：POST /posts 返回 id=101，
    但该资源并未真正创建，随后 GET /posts/101 返回 404。
    「创建后立即查询」的断言在本环境必然失败，因此标记为 xfail。

    验证链路前需确认被测环境是否真的持久化数据，
    否则实际验证的是 mock 服务的行为，而非业务逻辑。
    指向真实接口时移除该用例的 xfail 标记即可。
    """

    def test_created_post_returns_id(self, client: ApiClient, created_post: dict):
        """创建成功应返回新资源 id 并回显数据。"""
        post_id = created_post.get("id")
        assert post_id is not None, "创建接口应返回 id"
        assert created_post.get("title") == "fixture-temp", "应回显提交的标题"

    @pytest.mark.xfail(
        reason="jsonplaceholder 不持久化：创建返回 id=101，但 GET /posts/101 是 404。"
               "真实接口上此用例应通过。",
        strict=False,
    )
    def test_created_post_is_queryable(self, client: ApiClient, created_post: dict):
        """创建后立即可查 —— 这条链路专门用来暴露缓存 / 主从延迟类 bug。"""
        post_id = created_post["id"]
        resp = client.get(f"/posts/{post_id}")
        assert_status(resp, 200, "刚创建的资源应能查到")
