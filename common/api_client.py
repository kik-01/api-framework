"""统一的请求封装。

设计说明：
- 为什么不直接在用例里写 requests.get()？
  → 因为真实项目要统一加 token、统一超时、统一日志、统一异常处理。
    散落在 100 个用例里的 requests.get() 是不可维护的。
- 为什么返回 Response 而不是直接返回 json？
  → 用例有时要断言状态码、有时要断言响应头，直接返回 json 会丢信息。
"""

from __future__ import annotations

import json
import time
from typing import Any

import requests

from common.logger import get_logger
from common.settings import CONFIG

log = get_logger(__name__)


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
        """发请求，带自动重试。

        ⚠️ 为什么需要重试（踩坑记录 #1 的延伸）：
        第一次跑用例时 /posts 列表接口 Read timed out。
        一开始我以为是框架写错了，其实是**公开 API 本身不稳**：
        同样的请求，有时 300ms 返回，有时 30 秒都不回。

        教训：**断言"被测服务稳定"是测试的假设，不是事实。**
             对不稳定的外部依赖，要么加重试，要么明确标记为不稳定用例。
             真实项目里，内网接口一般不需要重试；
             但走公网 / 第三方依赖的用例，几乎都必须重试。

        注意：**只对"连接类错误"和 5xx 重试，不能对 4xx 重试** ——
             4xx 是客户端错误，重试多少次都一样，只会拖慢测试。
        """
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        max_attempts = (retries if retries is not None else CONFIG.get("retries", 2)) + 1
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            start = time.time()
            try:
                resp = self.session.request(
                    method.upper(),
                    url,
                    params=params,
                    json=json_body,
                    data=data,
                    headers=headers,
                    timeout=self.timeout,
                    **kwargs,
                )
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_exc = exc
                log.warning(
                    "请求失败(第 %d/%d 次) [%s] %s -> %s",
                    attempt, max_attempts, method.upper(), url, type(exc).__name__,
                )
                if attempt < max_attempts:
                    time.sleep(1.5 * attempt)   # 退避：越往后等越久
                    continue
                log.error("请求最终失败 [%s] %s (%.2fs)", method.upper(), url, time.time() - start)
                raise

            # 5xx 是服务端抖动，值得重试；4xx 不重试
            if resp.status_code >= 500 and attempt < max_attempts:
                log.warning(
                    "服务端 %d，重试(第 %d/%d 次) [%s] %s",
                    resp.status_code, attempt, max_attempts, method.upper(), url,
                )
                time.sleep(1.5 * attempt)
                continue

            cost = time.time() - start
            if CONFIG.get("verbose"):
                log.info(
                    "[%s] %s -> %s (%.0fms)%s",
                    method.upper(),
                    url,
                    resp.status_code,
                    cost * 1000,
                    f"  [第{attempt}次尝试]" if attempt > 1 else "",
                )
                log.debug("请求参数: %s", json.dumps(params or json_body, ensure_ascii=False, default=str))
                log.debug("响应内容: %s", resp.text[:800])

            return resp

        # 理论上到不了这里，兜底
        if last_exc:
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
