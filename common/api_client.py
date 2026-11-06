"""统一的 HTTP 请求封装。

所有请求经由此类发出，集中处理鉴权、超时、日志与异常，
避免同类逻辑散落在各用例中难以维护。
返回 Response 对象而非解析后的 JSON，保留状态码与响应头供上层断言。
"""

from __future__ import annotations

import json
import time
from typing import Any

import requests

from common.logger import get_logger, mask_sensitive
from common.settings import CONFIG

log = get_logger(__name__)

# 只有这些方法在失败后重试是安全的：服务端重复执行不会改变结果。
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# 值得重试的瞬态异常。
# 注意 SSLError 也在其中（它是 ConnectionError 的子类），
# 但证书错误是确定性失败，必须单独拦下，所以下面先 except SSLError。
RETRYABLE_EXCEPTIONS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,   # 传输中途断开，属于瞬态
)


class ApiClient:
    """一个极简但结构正确的 HTTP 客户端封装。

    真实项目里通常还会加：
      - 重试机制（tenacity）
      - 请求签名
      - 加解密
      - 会话保持（这里已用 Session）
    """

    def __init__(self, base_url: str | None = None, timeout: int | None = None):
        self.base_url = (base_url or CONFIG["base_url"]).rstrip("/")
        self.timeout = timeout or CONFIG.get("timeout", 10)
        self.session = requests.Session()
        # 统一默认请求头：真实项目里 UA、App-Version 这类都放这里
        self.session.headers.update(
            {
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": "pytest-api-framework/1.0",
            }
        )

    # ---------- 认证 ----------

    def set_token(self, token: str, header_name: str = "Authorization") -> None:
        """设置鉴权头。真实项目里 token 通常由登录接口动态获取后调这里。"""
        self.session.headers[header_name] = token

    def clear_token(self, header_name: str = "Authorization") -> None:
        self.session.headers.pop(header_name, None)

    # ---------- 核心请求 ----------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: Any = None,
        data: Any = None,
        headers: dict | None = None,
        retries: int | None = None,
        **kwargs,
    ) -> requests.Response:
        """发送请求，带自动重试（写操作默认不重试）。

重试策略：
  1. 只重试幂等方法（GET / HEAD / OPTIONS）。
     POST / PUT / PATCH / DELETE 默认 0 次重试 —— 读超时说明请求**可能已经被处理**，
     此时重试会重复写入。要重试必须由调用方显式传 retries=N，
     且上游接口需支持幂等键，否则宁可报错让人看。
  2. 只重试瞬态异常（超时 / 连接错误 / 传输中断）与 5xx。
     4xx 是确定性错误，重试不会改变结果；SSL 证书错误同样不重试。
  3. 重试有总时长上限（config.yaml 的 retry_budget_seconds），
     避免「3 次 × 30s 超时 + 退避」把一条用例拖到 100 秒。
  4. 返回的 Response 上额外挂了 total_elapsed（含重试与退避的总耗时）
     和 attempts（实际尝试次数），供性能断言使用。
        """
        method_name = method.upper()
        url = path if path.startswith("http") else f"{self.base_url}{path}"

        if retries is not None:
            configured = retries
        elif method_name in IDEMPOTENT_METHODS:
            configured = CONFIG.get("retries", 2)
        else:
            configured = 0      # 写操作：默认不重试，杜绝重复写入
        max_attempts = configured + 1
        retry_budget = float(CONFIG.get("retry_budget_seconds", 45))

        start_all = time.monotonic()
        deadline = start_all + retry_budget
        last_exc: Exception | None = None
        last_resp: requests.Response | None = None

        for attempt in range(1, max_attempts + 1):
            # 预算控制：已经等了太久就不再开新的一次尝试
            if attempt > 1 and time.monotonic() >= deadline:
                log.error(
                    "重试预算 %.1fs 已用尽，停止重试 [%s] %s", retry_budget, method_name, url
                )
                if last_resp is not None:
                    return last_resp
                if last_exc is not None:
                    raise last_exc
                break

            start = time.monotonic()
            try:
                resp = self.session.request(
                    method_name,
                    url,
                    params=params,
                    json=json_body,
                    data=data,
                    headers=headers,
                    timeout=self.timeout,
                    **kwargs,
                )
            except requests.exceptions.SSLError as exc:
                # 证书 / 握手错误是确定性失败，重试只会白白消耗时间
                log.error(
                    "TLS 证书错误，不重试 [%s] %s: %s", method_name, url, type(exc).__name__
                )
                raise
            except RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                log.warning(
                    "请求失败(第 %d/%d 次) [%s] %s -> %s",
                    attempt, max_attempts, method_name, url, type(exc).__name__,
                )
                if attempt < max_attempts:
                    time.sleep(1.5 * attempt)   # 线性退避：越往后等越久
                    continue
                log.error(
                    "请求最终失败 [%s] %s (%.2fs)", method_name, url, time.monotonic() - start
                )
                raise

            last_resp = resp

            # 5xx 是服务端抖动，值得重试；4xx 不重试
            if resp.status_code >= 500 and attempt < max_attempts:
                log.warning(
                    "服务端 %d，重试(第 %d/%d 次) [%s] %s",
                    resp.status_code, attempt, max_attempts, method_name, url,
                )
                time.sleep(1.5 * attempt)
                continue

            cost = time.monotonic() - start
            # 挂到 Response 上：性能断言用这个值，才不会被重试「平均」掉
            resp.total_elapsed = time.monotonic() - start_all     # noqa: attribute-defined-outside-init
            resp.attempts = attempt                                # noqa: attribute-defined-outside-init
            if CONFIG.get("verbose"):
                log.info(
                    "[%s] %s -> %s (%.0fms)%s",
                    method_name,
                    url,
                    resp.status_code,
                    cost * 1000,
                    f"  [第{attempt}次尝试]" if attempt > 1 else "",
                )
                log.debug(
                    "请求参数: %s",
                    mask_sensitive(json.dumps(params or json_body, ensure_ascii=False, default=str)),
                )
                log.debug("响应内容: %s", mask_sensitive(resp.text[:800]))

            return resp

        # 理论上到不了这里，兜底
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"请求未能完成: {method} {url}")

    # 便捷方法：让用例写起来更像自然语言
    def get(self, path: str, **kwargs) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> requests.Response:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs) -> requests.Response:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        return self.request("DELETE", path, **kwargs)
