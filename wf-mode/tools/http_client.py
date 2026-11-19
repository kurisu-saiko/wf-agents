"""薄 HTTP 客户端（支持 httpx 与 stdlib urllib 自动回退）。

只做请求、重试、状态码映射和 JSON/文本解析；不记录请求头，不打印密钥。
"""

from __future__ import annotations

import json
import os
import socket
import time
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

try:
    import httpx  # type: ignore
except ImportError:  # pragma: no cover - 运行在纯 stdlib 环境时触发
    httpx = None  # type: ignore

from tools import config as local_config
from tools.errors import ToolError

USER_AGENT = "wf-tool/0.2 (+universal-workflow-plugin)"
MAX_RETRIES = 2
MAX_RETRY_AFTER = 5.0
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def _timeout(override: float | None = None) -> float:
    if override is not None:
        return max(1.0, float(override))
    try:
        return max(1.0, float(os.environ.get("WF_HTTP_TIMEOUT", "20")))
    except ValueError:
        return 20.0


def _max_retries() -> int:
    try:
        return max(0, min(4, int(os.environ.get("WF_HTTP_RETRIES", str(MAX_RETRIES)))))
    except ValueError:
        return MAX_RETRIES


def _retry_delay(attempt: int, retry_after: str | None = None) -> float:
    if retry_after:
        try:
            seconds = float(retry_after.strip())
            if seconds > 0:
                return min(MAX_RETRY_AFTER, seconds)
        except ValueError:
            pass
    return min(MAX_RETRY_AFTER, 0.5 * (2**attempt))


def _safe_hint(raw_text: str) -> str:
    cleaned = " ".join((raw_text or "").split())
    if not cleaned:
        return ""
    return local_config.redact(cleaned[:240])


def _header_ci(headers: Any, name: str) -> str:
    if not headers:
        return ""
    target = name.lower()
    for key, value in dict(headers).items():
        if str(key).lower() == target:
            return str(value)
    return ""


def _build_http_error(
    status: int,
    provider: str,
    headers: Any = None,
    body_text: str = "",
) -> ToolError:
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

    details: dict[str, Any] = {"provider": provider, "status": status}
    remaining = _header_ci(headers, "x-ratelimit-remaining") or _header_ci(headers, "ratelimit-remaining")
    reset = _header_ci(headers, "x-ratelimit-reset") or _header_ci(headers, "ratelimit-reset")
    if remaining:
        details["rateLimitRemaining"] = remaining
    if reset:
        details["rateLimitReset"] = reset
    hint = _safe_hint(body_text)
    if hint:
        details["hint"] = hint

    return ToolError(
        code,
        f"{provider} 返回 HTTP {status}",
        retryable=retryable,
        details=details,
        allow_fallback=True,
    )


def _request_httpx(
    method: str,
    url: str,
    *,
    provider: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    json_body: dict[str, Any] | None,
    data_body: bytes | None,
    timeout: float,
) -> tuple[int, dict[str, str], str]:
    assert httpx is not None
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                content=data_body,
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
    return response.status_code, dict(response.headers), response.text


def _request_urllib(
    method: str,
    url: str,
    *,
    provider: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    json_body: dict[str, Any] | None,
    data_body: bytes | None,
    timeout: float,
) -> tuple[int, dict[str, str], str]:
    target_url = url
    if params:
        encoded = urlparse.urlencode(
            [(k, v) for k, v in params.items() if v is not None],
            doseq=True,
        )
        if encoded:
            sep = "&" if "?" in target_url else "?"
            target_url = f"{target_url}{sep}{encoded}"

    req_headers = dict(headers)
    body: bytes | None = data_body
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")

    req = urlrequest.Request(target_url, data=body, headers=req_headers, method=method)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return int(getattr(response, "status", 200)), dict(response.headers), raw
    except urlerror.HTTPError as exc:
        try:
            body_text = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body_text = ""
        return int(exc.code), dict(exc.headers or {}), body_text
    except (TimeoutError, socket.timeout) as exc:
        raise ToolError(
            "TIMEOUT",
            f"{provider} 请求超时",
            retryable=True,
            details={"provider": provider},
            allow_fallback=True,
        ) from exc
    except urlerror.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise ToolError(
                "TIMEOUT",
                f"{provider} 请求超时",
                retryable=True,
                details={"provider": provider},
                allow_fallback=True,
            ) from exc
        raise ToolError(
            "UPSTREAM_ERROR",
            f"{provider} 网络请求失败",
            retryable=True,
            details={"provider": provider, "error": type(exc.reason).__name__ if exc.reason else type(exc).__name__},
            allow_fallback=True,
        ) from exc
    except OSError as exc:
        raise ToolError(
            "UPSTREAM_ERROR",
            f"{provider} 网络请求失败",
            retryable=True,
            details={"provider": provider, "error": type(exc).__name__},
            allow_fallback=True,
        ) from exc


def _request(
    method: str,
    url: str,
    *,
    provider: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    data_body: bytes | None = None,
    timeout: float | None = None,
) -> str:
    merged = {"User-Agent": USER_AGENT}
    if headers:
        merged.update(headers)

    effective_timeout = _timeout(timeout)
    retries = _max_retries()
    backend = _request_httpx if httpx is not None else _request_urllib

    for attempt in range(retries + 1):
        try:
            status, resp_headers, text = backend(
                method,
                url,
                provider=provider,
                headers=merged,
                params=params,
                json_body=json_body,
                data_body=data_body,
                timeout=effective_timeout,
            )
        except ToolError as exc:
            if exc.retryable and attempt < retries:
                time.sleep(_retry_delay(attempt))
                continue
            raise

        if status < 400:
            return text

        if status in RETRYABLE_STATUSES and attempt < retries:
            retry_after = _header_ci(resp_headers, "retry-after")
            time.sleep(_retry_delay(attempt, retry_after))
            continue

        raise _build_http_error(status, provider, resp_headers, text)

    raise ToolError("UPSTREAM_ERROR", f"{provider} 请求失败", details={"provider": provider}, allow_fallback=True)


def post_json(
    url: str,
    body: dict[str, Any],
    *,
    provider: str,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    text = _request(
        "POST",
        url,
        provider=provider,
        headers=headers,
        json_body=body,
        timeout=timeout,
    )
    try:
        data = json.loads(text)
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


def post_json_any(
    url: str,
    body: dict[str, Any],
    *,
    provider: str,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> Any:
    text = _request(
        "POST",
        url,
        provider=provider,
        headers=headers,
        json_body=body,
        timeout=timeout,
    )
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ToolError(
            "UPSTREAM_ERROR",
            f"{provider} 返回的不是 JSON",
            details={"provider": provider},
            allow_fallback=True,
        ) from exc


def get_json_any(
    url: str,
    *,
    provider: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> Any:
    text = _request(
        "GET",
        url,
        provider=provider,
        headers=headers,
        params=params,
        timeout=timeout,
    )
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ToolError(
            "UPSTREAM_ERROR",
            f"{provider} 返回的不是 JSON",
            details={"provider": provider},
            allow_fallback=True,
        ) from exc


def get_json(
    url: str,
    *,
    provider: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    data = get_json_any(
        url,
        provider=provider,
        headers=headers,
        params=params,
        timeout=timeout,
    )
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
    params: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> str:
    return _request(
        "GET",
        url,
        provider=provider,
        headers=headers,
        params=params,
        timeout=timeout,
    )
