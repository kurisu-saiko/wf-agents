"""web_extract：Firecrawl -> Jina Reader -> Direct（高保真零密钥 HTML/Markdown/GitHub 抽取）。"""

from __future__ import annotations

import base64
import re
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urlparse

from tools import cache, http_client, repo_utils
from tools.errors import ToolError
from tools.util import first_env, utc_now

SLOT = "web_extract"
ACTIONS = ("extract", "health")
PROVIDERS = ("firecrawl", "jina", "direct")
DEFAULT_MAX_CHARS = 24000
MAX_CHARS_CAP = 60000

_GITHUB_BLOB_RE = re.compile(r"^/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$")
_GITHUB_ROOT_RE = re.compile(r"^/([^/]+)/([^/]+)/?$")


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
        return max(1000, min(MAX_CHARS_CAP, int(raw)))
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


def _github_root_repo(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if parsed.netloc.lower() in {"github.com", "www.github.com"}:
        match = _GITHUB_ROOT_RE.match(parsed.path)
        if match:
            owner, repo = match.groups()
            if owner not in {"orgs", "users", "topics", "search", "explore", "settings"}:
                return owner, repo.removesuffix(".git")
    return None


class _ReadableHTMLParser(HTMLParser):
    """零依赖 HTML -> 高保真 Markdown 抽取器（保留链接、代码块语言、表格、引用与标题）。"""

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
        self._in_link = False
        self._link_href = ""
        self._link_text: list[str] = []
        self._title_buf: list[str] = []
        self._chunks: list[str] = []
        self._main_chunks: list[str] = []
        self._main_depth = 0
        self._row_cells: list[str] = []
        self._in_cell = False
        self._cell_buf: list[str] = []

    def _emit(self, text: str) -> None:
        self._chunks.append(text)
        if self._main_depth > 0:
            self._main_chunks.append(text)

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

        if t in {"main", "article"}:
            self._main_depth += 1

        if t == "title":
            self._in_title = True
        elif t in self.HEADING_LEVEL:
            self._emit("\n\n" + self.HEADING_LEVEL[t])
        elif t in {"p", "section"}:
            self._emit("\n\n")
        elif t == "blockquote":
            self._emit("\n\n> ")
        elif t == "hr":
            self._emit("\n\n---\n\n")
        elif t == "br":
            self._emit("\n")
        elif t == "li":
            self._emit("\n- ")
        elif t == "tr":
            self._row_cells = []
        elif t in {"th", "td"}:
            self._in_cell = True
            self._cell_buf = []
        elif t == "pre":
            self._in_pre = True
            self._emit("\n\n```")
        elif t == "code":
            if self._in_pre:
                cls = attr_map.get("class") or ""
                lang_match = re.search(r"language-([A-Za-z0-9_+-]+)", cls)
                lang = lang_match.group(1) if lang_match else ""
                self._emit(lang + "\n")
            else:
                self._in_code = True
                self._emit("`")
        elif t == "a":
            href = attr_map.get("href") or ""
            if href.startswith(("http://", "https://")):
                self._in_link = True
                self._link_href = href
                self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth > 0:
            return

        if t in {"main", "article"}:
            self._main_depth = max(0, self._main_depth - 1)

        if t == "title":
            self._in_title = False
            self.title = " ".join("".join(self._title_buf).split())
        elif t in self.HEADING_LEVEL or t in {"p", "li", "blockquote"}:
            self._emit("\n")
        elif t in {"th", "td"} and self._in_cell:
            self._in_cell = False
            self._row_cells.append(" ".join("".join(self._cell_buf).split()))
        elif t == "tr" and self._row_cells:
            self._emit("\n| " + " | ".join(self._row_cells) + " |")
            self._row_cells = []
        elif t == "pre":
            self._in_pre = False
            self._emit("\n```\n\n")
        elif t == "code" and not self._in_pre and self._in_code:
            self._in_code = False
            self._emit("`")
        elif t == "a" and self._in_link:
            self._in_link = False
            label = " ".join("".join(self._link_text).split())
            if label:
                self._emit(f"[{label}]({self._link_href})")
            self._link_href = ""
            self._link_text = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_buf.append(data)
            return
        if self._skip_depth > 0:
            return
        if self._in_cell:
            self._cell_buf.append(data)
            return
        if self._in_link:
            self._link_text.append(data)
            return
        if self._in_pre:
            self._emit(data)
        else:
            collapsed = re.sub(r"[ \t\r\n]+", " ", data)
            if collapsed:
                self._emit(collapsed)

    def markdown(self) -> str:
        main_text = re.sub(r"\n{3,}", "\n\n", "".join(self._main_chunks)).strip()
        full_text = re.sub(r"\n{3,}", "\n\n", "".join(self._chunks)).strip()
        # 当页面存在实质性的 <main>/<article> 时优先返回主内容，剔除边缘噪音
        if len(main_text) >= 120:
            return main_text
        return full_text


def html_to_markdown(raw_text: str) -> tuple[str, str, str]:
    """将 HTML 转换为紧凑 Markdown 并提取 title / publishedTime；非 HTML 原文直出。"""
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


def _extract_github_root(owner: str, repo: str, url: str, limit: int) -> dict[str, Any]:
    meta = http_client.get_json(
        f"https://api.github.com/repos/{owner}/{repo}",
        headers=repo_utils.github_headers(),
        provider="direct",
    )
    readme_text = ""
    try:
        rd = http_client.get_json(
            f"https://api.github.com/repos/{owner}/{repo}/readme",
            headers=repo_utils.github_headers(),
            provider="direct",
        )
        b64 = str(rd.get("content") or "")
        if b64:
            readme_text = base64.b64decode(b64).decode("utf-8", errors="replace")
    except ToolError:
        readme_text = ""

    lic = (meta.get("license") or {}).get("spdx_id") if isinstance(meta.get("license"), dict) else ""
    header = (
        f"# {meta.get('full_name') or f'{owner}/{repo}'}\n\n"
        f"{meta.get('description') or ''}\n\n"
        f"- Stars: {meta.get('stargazers_count', 0)} | License: {lic or 'UNKNOWN'} | "
        f"Language: {meta.get('language') or '-'} | Pushed: {meta.get('pushed_at') or '-'}\n\n"
    )
    return {
        "url": url,
        "fetchedUrl": f"https://api.github.com/repos/{owner}/{repo}",
        "title": str(meta.get("full_name") or f"{owner}/{repo}"),
        "text": (header + readme_text)[:limit],
        "metadata": {
            "provider": "direct",
            "fetchedAt": utc_now(),
            "publishedTime": str(meta.get("pushed_at") or ""),
        },
    }


def _extract_direct(payload: dict[str, Any]) -> dict[str, Any]:
    url = _url(payload)
    limit = _max_chars(payload)
    fetch_url = normalize_fetch_url(url)
    cache_key = cache.make_key(fetch_url, limit)
    cached = cache.get(SLOT, "direct", cache_key)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached

    gh_root = _github_root_repo(url)
    if gh_root is not None:
        try:
            output = _extract_github_root(gh_root[0], gh_root[1], url, limit)
            cache.put(SLOT, "direct", cache_key, output)
            output["_cached"] = False
            return output
        except ToolError:
            pass

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
