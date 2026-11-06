"""「接口返回」与「数据库落库」一致性校验。

HTTP 200/201 只代表服务端处理完请求，不代表数据已写入数据库。
异步写、事务回滚、主从延迟都会导致两者不一致，
只断言状态码与响应体的测试在这些情况下仍会通过，实际未验证任何数据。

本组用例做查库对账：用接口返回的 id 查询数据库并比对字段值。
被测服务为 common/local_api.py，其 /users/broken 端点返回 200 但不写库，
用于验证查库校验能识别这种假成功。
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from common.validators import assert_status


class TestDbConsistency:
    """接口返回成功之后，数据必须真的在库里。"""

    @pytest.mark.smoke
    def test_create_user_is_persisted(self, local_api):
        """创建用户：201 + 库里真的查得到 + 字段与请求一致。

        这是最基本的「查库对账」：只看 201 是不够的。
        """
        client, db = local_api["client"], local_api["db"]

        resp = client.post("/users", json_body={"name": "张三", "city": "广州"})
        assert_status(resp, 201, "创建用户")
        uid = resp.json()["id"]

        row = db.query_one("SELECT * FROM users WHERE id = ?", (uid,))
        assert row is not None, (
            f"接口返回 201（id={uid}），但库里查不到这条记录 —— "
            f"说明数据没有真正落库，仅断言状态码无法发现该问题。"
        )
        assert row["name"] == "张三", "库里 name 与请求不一致"
        assert row["city"] == "广州", "库里 city 与请求不一致"

    def test_count_increases_by_one(self, local_api):
        """每创建一条，库里的记录必须 +1，且同一份数据只能有 1 条。

        比「查得到」更进一层：验证的是**没有多写、也没有少写**。
        接口偶尔会因为重试机制导致重复写入，只有数行数才能发现。

        这里用唯一名字做数据隔离：按名字计数，即使别的用例也在写库，
        本用例的结论依然成立；全表计数只作为辅助断言保留。
        """
        client, db = local_api["client"], local_api["db"]

        unique_name = f"李四-{uuid4().hex[:8]}"
        before_total = db.count("users")
        assert db.count("users", "name = ?", (unique_name,)) == 0, "测试数据名应唯一"

        resp = client.post("/users", json_body={"name": unique_name, "city": "深圳"})
        assert_status(resp, 201, "创建用户")

        named_rows = db.count("users", "name = ?", (unique_name,))
        assert named_rows == 1, (
            f"同一份数据应只落库 1 条，实际 {named_rows} 条。"
            f"多了说明写操作被重试导致重复写入（检查重试是否只作用于幂等方法）"
        )

        after_total = db.count("users")
        assert after_total == before_total + 1, (
            f"创建一条记录后全表行数应 +1，实际 {before_total} -> {after_total}。"
            f"少了说明没落库"
        )

    @pytest.mark.smoke
    def test_fake_success_can_be_detected(self, local_api):
        """证明查库校验的价值：接口说 200，但库里没有 —— 我们能发现。

        /users/broken 是故意做成「假成功」的端点。
        这条用例本身是**通过**的，因为它验证的是「校验机制确实有效」：
        只要我们查库，就一定能抓到这种假象。

        这条用例的设计意图：
            专门构造一个「返回 200 但不落库」的端点，用来验证查库校验本身是否有效。
            如果哪天有人把查库那步删了，这条用例就抓不出来 —— 它是校验机制的哨兵。
        """
        client, db = local_api["client"], local_api["db"]

        resp = client.post("/users/broken", json_body={"name": "王五", "city": "东莞"})
        assert resp.status_code == 200, "这个端点故意返回 200"

        persisted = db.count("users", "name = ?", ("王五",))
        assert persisted == 0, (
            "这个端点的设计就是「返回 200 但不写库」。"
            "如果这里查到了数据，说明服务实现被改了，这条用例要跟着调整。"
        )

    def test_get_missing_user_returns_404_and_no_row(self, local_api):
        """异常场景也要对账：返回 404 的同时，库里确实没有这条数据。"""
        client, db = local_api["client"], local_api["db"]

        resp = client.get("/users/999999")
        assert_status(resp, 404, "查询不存在的用户")

        assert db.count("users", "id = ?", (999999,)) == 0, "库里不该存在这个 id"


class TestDbHelpers:
    """顺手验证 db 封装本身的行为，避免「校验工具自己坏了还继续跑」。"""

    def test_ping(self, local_api):
        assert local_api["db"].ping() is True

    def test_query_one_returns_none_when_missing(self, local_api):
        assert local_api["db"].query_one("SELECT * FROM users WHERE id = ?", (-1,)) is None
