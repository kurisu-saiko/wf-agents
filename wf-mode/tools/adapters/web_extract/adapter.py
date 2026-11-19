"""web_extract：Firecrawl -> Jina Reader -> Direct（零密钥内置 HTML/Markdown 抽取）。"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urlparse

from tools import cache, http_client
from tools.errors import ToolError
from tools.util import first_env, utc_now

SLOT = "web_extract"
ACTIONS = ("extract", "health")
PROVIDERS = ("firecrawl", "jina", "direct")
DEFAULT_MAX_CHARS = 24000
MAX_CHARS_CAP = 60000

_GITHUB_BLOB_RE = re.compile(r"^/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$")


def _url(payload: dict[str, Any]) -> str:
    raw = payload.get("url")
    if not isinstance(raw, str) or not raw.strip():
        raise ToolError("INVALID_INPUT", "url 必须是非空字符串")
    url = raw.strip()
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ToolError("INVALID_INPUT", "url 必须是 http/https 地址")
    return url


def _max_chars(payload: dict[str, Any]) -> int:
    raw = payload.get("maxChars")
    if raw is None or raw == "":
        return DEFAULT_MAX_CHARS
    try:
        val = int(raw)
        return max(1000, min(MAX_CHARS_CAP, val))
    except (TypeError, ValueError) as exc:
        raise ToolError("INVALID_INPUT", "maxChars 必须是整数") from exc


def normalize_fetch_url(url: str) -> str:
    """将 GitHub blob 页面转换为 raw.githubusercontent.com 以获取纯净原文。"""
    parsed = urlparse(url)
    if parsed.netloc.lower() in {"github.com", "www.github.com"}:
        match = _GITHUB_BLOB_RE.match(parsed.path)
        if match:
            owner, repo, ref, path = match.groups()
            return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
    return url


class _ReadableHTMLParser(HTMLParser):
    """零依赖 HTML -> 紧凑 Markdown 文本抽取器。"""

    SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "aside", "template"}
    HEADING_LEVEL = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### "}

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.published = ""
        self.description = ""
        self._skip_depth = 0
        self._in_title = False
        self._in_pre = False
        self._in_code = False
        self._title_buf: list[str] = []
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        attr_map = {str(k).lower(): str(v or "") for k, v in attrs}
        if t == "meta":
            name = (attr_map.get("name") or attr_map.get("property") or "").lower()
            content = attr_map.get("content") or ""
            if name in {"article:published_time", "og:published_time", "publishedtime", "date"} and not self.published:
                self.published = content
            elif name in {"description", "og:description"} and not self.description:
                self.description = content
            return

        if t in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return

        if t == "title":
            self._in_title = True
        elif t in self.HEADING_LEVEL:
            self._chunks.append("\n\n" + self.HEADING_LEVEL[t])
        elif t in {"p", "section", "article", "tr"}:
            self._chunks.append("\n\n")
        elif t == "br":
            self._chunks.append("\n")
        elif t == "li":
            self._chunks.append("\n- ")
        elif t == "pre":
            self._in_pre = True
            self._chunks.append("\n\n```\n")
        elif t == "code" and not self._in_pre:
            self._in_code = True
            self._chunks.append("`")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth > 0:
            return
        if t == "title":
            self._in_title = False
            self.title = " ".join("".join(self._title_buf).split())
        elif t in self.HEADING_LEVEL or t in {"p", "li"}:
            self._chunks.append("\n")
        elif t == "pre":
            self._in_pre = False
            self._chunks.append("\n```\n\n")
        elif t == "code" and not self._in_pre and self._in_code:
            self._in_code = False
            self._chunks.append("`")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_buf.append(data)
            return
        if self._skip_depth > 0:
            return
        if self._in_pre:
            self._chunks.append(data)
        else:
            collapsed = re.sub(r"[ \t\r\n]+", " ", data)
            if collapsed:
                self._chunks.append(collapsed)

    def markdown(self) -> str:
        joined = "".join(self._chunks)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return joined.strip()


def html_to_markdown(raw_text: str) -> tuple[str, str, str]:
    """将 HTML 转换为紧凑文本并提取 title / publishedTime；非 HTML 原文直出。"""
    head = (raw_text or "")[:1200].lower()
    if not any(marker in head for marker in ("<html", "<!doctype", "<head", "<body", "<article", "<main")):
        return "", "", (raw_text or "").strip()
    parser = _ReadableHTMLParser()
    parser.feed(raw_text)
    parser.close()
    text = parser.markdown()
    if not text and parser.description:
        text = parser.description
    return parser.title, parser.published, text


def _extract_firecrawl(payload: dict[str, Any]) -> dict[str, Any]:
    key, _ = first_env("FIRECRAWL_API_KEY", "FIRECRAWL")
    if not key:
        raise ToolError(
            "AUTH_MISSING",
            "FIRECRAWL_API_KEY/FIRECRAWL 未配置",
            details={"provider": "firecrawl", "env": "FIRECRAWL_API_KEY|FIRECRAWL"},
            allow_fallback=True,
        )
    url = _url(payload)
    limit = _max_chars(payload)
    cache_key = cache.make_key(url, limit)
    cached = cache.get(SLOT, "firecrawl", cache_key)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached
    data = http_client.post_json(
        "https://api.firecrawl.dev/v1/scrape",
        {"url": url, "formats": ["markdown"], "onlyMainContent": True},
        headers={"Authorization": f"Bearer {key}"},
        provider="firecrawl",
    )
    body = data.get("data") if isinstance(data.get("data"), dict) else data
    text = str(body.get("markdown") or body.get("content") or "")
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    published = (
        metadata.get("publishedTime")
        or metadata.get("modifiedTime")
        or metadata.get("og:published_time")
        or metadata.get("article:published_time")
        or metadata.get("date")
        or ""
    )
    output = {
        "url": url,
        "title": str(metadata.get("title") or ""),
        "text": text[:limit],
        "metadata": {
            "provider": "firecrawl",
            "fetchedAt": utc_now(),
            "publishedTime": str(published),
        },
    }
    cache.put(SLOT, "firecrawl", cache_key, output)
    output["_cached"] = False
    return output


def _extract_jina(payload: dict[str, Any]) -> dict[str, Any]:
    url = _url(payload)
    limit = _max_chars(payload)
    cache_key = cache.make_key(url, limit)
    cached = cache.get(SLOT, "jina", cache_key)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached
    headers = {"Accept": "text/plain"}
    key, _ = first_env("JINA_API_KEY", "JINA")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    text = http_client.get_text(f"https://r.jina.ai/{url}", headers=headers, provider="jina")
    output = {
        "url": url,
        "title": "",
        "text": text[:limit],
        "metadata": {
            "provider": "jina",
            "fetchedAt": utc_now(),
            "publishedTime": "",
        },
    }
    cache.put(SLOT, "jina", cache_key, output)
    output["_cached"] = False
    return output


def _extract_direct(payload: dict[str, Any]) -> dict[str, Any]:
    url = _url(payload)
    limit = _max_chars(payload)
    fetch_url = normalize_fetch_url(url)
    cache_key = cache.make_key(fetch_url, limit)
    cached = cache.get(SLOT, "direct", cache_key)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached

    raw = http_client.get_text(
        fetch_url,
        headers={"Accept": "text/markdown, text/plain, text/html;q=0.9, */*;q=0.8"},
        provider="direct",
    )
    title, published, text = html_to_markdown(raw)
    output = {
        "url": url,
        "fetchedUrl": fetch_url,
        "title": title,
        "text": text[:limit],
        "metadata": {
            "provider": "direct",
            "fetchedAt": utc_now(),
            "publishedTime": published,
        },
    }
    cache.put(SLOT, "direct", cache_key, output)
    output["_cached"] = False
    return output


PROVIDER_FUNCS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "firecrawl": _extract_firecrawl,
    "jina": _extract_jina,
    "direct": _extract_direct,
}


def health(provider: str = "firecrawl") -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ToolError("INVALID_INPUT", f"未知 provider: {provider}")
    if provider == "firecrawl":
        key, env_name = first_env("FIRECRAWL_API_KEY", "FIRECRAWL")
        configured = bool(key)
    elif provider == "jina":
        _, env_name = first_env("JINA_API_KEY", "JINA")
        configured = True
    else:
        env_name = ""
        configured = True
    return {
        "ok": configured,
        "provider": provider,
        "configured": configured,
        "env": env_name,
        "checkedAt": utc_now(),
    }


def execute(action: str, payload: dict[str, Any], provider: str | None = None) -> dict[str, Any]:
    if action == "health":
        return health(provider or "firecrawl")
    if action != "extract":
        raise ToolError("UNKNOWN_ACTION", f"web_extract 不支持动作: {action}")
    chosen = provider or "firecrawl"
    func = PROVIDER_FUNCS.get(chosen)
    if func is None:
        raise ToolError("INVALID_INPUT", f"web_extract 未知 provider: {chosen}")
    return func(payload)
