"""断言工具。

设计说明：
- 为什么不直接用 assert？
  → 可以用。但真实项目里断言失败要**带上下文**，否则报告里只有
    "assert 200 == 404"，看不出请求发了什么、返回了什么。
    这里的 assert_status 会把响应体一起带进失败信息。
- 为什么单独写 response_schema 而不是引 jsonschema 库？
  → 为了少一个依赖。真实项目建议直接上 jsonschema，更严谨。
    这里手写校验是为了把结构校验逻辑显式化，避免依赖黑盒断言。
"""

from __future__ import annotations

from typing import Any

import requests


def assert_status(resp: requests.Response, expected: int, msg: str = "") -> None:
    """断言状态码，失败时把响应体一起打出来。"""
    actual = resp.status_code
    assert actual == expected, (
        f"{msg}\n"
        f"  期望状态码: {expected}\n"
        f"  实际状态码: {actual}\n"
        f"  请求地址: {resp.request.method} {resp.request.url}\n"
        f"  响应内容: {resp.text[:500]}"
    )


def assert_json_key(resp: requests.Response, key: str, msg: str = "") -> Any:
    """断言响应 JSON 里存在某个字段，并返回它的值。"""
    try:
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"{msg}\n  响应不是合法 JSON: {resp.text[:300]}") from exc

    assert key in body, (
        f"{msg}\n"
        f"  响应里没有字段 '{key}'\n"
        f"  实际字段列表: {list(body.keys()) if isinstance(body, dict) else type(body)}"
    )
    return body[key]


def assert_fields(resp: requests.Response, expected: dict, msg: str = "") -> None:
    """断言响应 JSON 里多个字段的值。

    用法：assert_fields(resp, {"id": 1, "userId": 1})
    """
    body = resp.json()
    mismatches = []
    for key, want in expected.items():
        got = body.get(key) if isinstance(body, dict) else None
        if got != want:
            mismatches.append(f"    {key}: 期望 {want!r}，实际 {got!r}")
    assert not mismatches, f"{msg}\n  字段值不匹配:\n" + "\n".join(mismatches)


def assert_schema(resp: requests.Response, schema: dict, msg: str = "") -> None:
    """极简结构校验：只检查字段是否存在和类型是否匹配。

    schema 形如：{"id": "int", "title": "str", "body": "str"}

    ⚠️ 踩坑记录 #3：类型名必须写成**字符串**。
    一开始我在 validators 里直接写 `isinstance(value, expected_type)`，
    想让 YAML 里的 `int` 当类型用 —— 结果报：
        TypeError: isinstance() arg 2 must be a type, a tuple of types, or a union
    因为 **YAML/JSON 里没有"类型"这个数据类型**，`int` 被解析成了字符串 "int"。
    所以这里要建一张 名字->类型 的映射表。
    这个坑在真实项目里也常见（配置文件驱动的校验都躲不过）。

    真实项目建议直接上 jsonschema 库，支持嵌套 / 必填 / 枚举 / 正则等。
    """
    TYPE_MAP = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "none": type(None),
    }

    body = resp.json()
    if not isinstance(body, dict):
        raise AssertionError(f"{msg}\n  期望响应是对象，实际是 {type(body).__name__}")

    problems = []
    for key, expected in schema.items():
        if key not in body:
            problems.append(f"    缺少字段: {key}")
            continue

        # 支持两种写法：传真实类型，或传类型名字符串（来自 YAML）
        if isinstance(expected, str):
            expected_type = TYPE_MAP.get(expected.lower())
            if expected_type is None:
                problems.append(
                    f"    字段 {key}: 无法识别的类型名 {expected!r}，"
                    f"可用: {sorted(TYPE_MAP)}"
                )
                continue
        else:
            expected_type = expected

        value = body[key]
        actual_type = type(value)

        # bool 是 int 的子类，必须特判，否则 True 会被当成 int 蒙混过关
        if expected_type is int and actual_type is bool:
            problems.append(f"    字段 {key}: 期望 int，实际 bool")
        elif expected_type is bool and actual_type is not bool:
            problems.append(f"    字段 {key}: 期望 bool，实际 {actual_type.__name__}")
        elif not isinstance(value, expected_type):
            problems.append(
                f"    字段 {key}: 期望 {expected_type.__name__}，实际 {actual_type.__name__}"
                f"（值: {value!r}）"
            )
    assert not problems, f"{msg}\n  结构校验失败:\n" + "\n".join(problems)


def assert_response_time(resp: requests.Response, max_ms: float, msg: str = "") -> None:
    """断言响应时间在阈值内（性能基线）。

    注意：这个值在不同网络/机器上波动大，真实项目里要放宽或用百分位统计。
    """
    elapsed_ms = resp.elapsed.total_seconds() * 1000
    assert elapsed_ms <= max_ms, (
        f"{msg}\n  响应超时: {elapsed_ms:.0f}ms > {max_ms:.0f}ms"
    )
