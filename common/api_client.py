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
        """发送请求，带自动重试。

只对连接类错误与 5xx 重试：4xx 属客户端错误，重试不会改变结果，只会拖慢执行。
重试次数与退避间隔在 config.yaml 中配置，内网接口可设为 0。
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
