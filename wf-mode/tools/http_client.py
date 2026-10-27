"""薄 HTTP 客户端。

只做请求、状态码映射和 JSON/文本解析；不记录请求头，不打印密钥。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from tools.errors import ToolError

USER_AGENT = "wf-tool/0.1 (+local pipeline)"


def _timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("WF_HTTP_TIMEOUT", "20")))
    except ValueError:
        return 20.0


def _map_http_error(response: httpx.Response, provider: str) -> ToolError:
    status = response.status_code
    if status in (401, 403):
        code = "AUTH_FAILED"
        retryable = False
    elif status == 429:
        code = "RATE_LIMIT"
        retryable = True
    elif 500 <= status < 600:
        code = "UPSTREAM_ERROR"
        retryable = True
    else:
        code = "UPSTREAM_ERROR"
        retryable = False
    # 只回传 provider/status，不回传响应体，避免把密钥或敏感内容带进账本。
    return ToolError(
        code,
        f"{provider} 返回 HTTP {status}",
        retryable=retryable,
        details={"provider": provider, "status": status},
        allow_fallback=True,
    )


def _request(
    method: str,
    url: str,
    *,
    provider: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> httpx.Response:
    merged = {"User-Agent": USER_AGENT}
    if headers:
        merged.update(headers)
    try:
        with httpx.Client(timeout=_timeout(), follow_redirects=True) as client:
            response = client.request(
                method,
                url,
                headers=merged,
                params=params,
                json=json_body,
            )
    except httpx.TimeoutException as exc:
        raise ToolError(
            "TIMEOUT",
            f"{provider} 请求超时",
            retryable=True,
            details={"provider": provider},
            allow_fallback=True,
        ) from exc
    except httpx.HTTPError as exc:
        raise ToolError(
            "UPSTREAM_ERROR",
            f"{provider} 网络请求失败",
            retryable=True,
            details={"provider": provider, "error": type(exc).__name__},
            allow_fallback=True,
        ) from exc

    if response.status_code >= 400:
        raise _map_http_error(response, provider)
    return response


def post_json(
    url: str,
    body: dict[str, Any],
    *,
    provider: str,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = _request("POST", url, provider=provider, headers=headers, json_body=body)
    try:
        data = response.json()
    except ValueError as exc:
        raise ToolError(
            "UPSTREAM_ERROR",
            f"{provider} 返回的不是 JSON",
            details={"provider": provider},
            allow_fallback=True,
        ) from exc
    if not isinstance(data, dict):
        raise ToolError(
            "UPSTREAM_ERROR",
            f"{provider} 返回 JSON 不是对象",
            details={"provider": provider},
            allow_fallback=True,
        )
    return data


def get_json(
    url: str,
    *,
    provider: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = _request("GET", url, provider=provider, headers=headers, params=params)
    try:
        data = response.json()
    except ValueError as exc:
        raise ToolError(
            "UPSTREAM_ERROR",
            f"{provider} 返回的不是 JSON",
            details={"provider": provider},
            allow_fallback=True,
        ) from exc
    if not isinstance(data, dict):
        raise ToolError(
            "UPSTREAM_ERROR",
            f"{provider} 返回 JSON 不是对象",
            details={"provider": provider},
            allow_fallback=True,
        )
    return data


def get_text(
    url: str,
    *,
    provider: str,
    headers: dict[str, str] | None = None,
) -> str:
    response = _request("GET", url, provider=provider, headers=headers)
    return response.text
