"""面板数据层：调用 wf-tool、读写提示词、启停与本地配置。

只做数据转换与最小 IO；不记录运行历史。
优先进程内直接调用 wf-tool，避免点击面板时频繁启动子进程。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from tools import config as wf_config  # noqa: E402
from tools import session as wf_session  # noqa: E402

TOOL = ROOT / "tools" / "wf-tool.py"
_DEFAULT_STATE = ROOT / "panel" / "state.json"
STATE = _DEFAULT_STATE
CATALOG = ROOT / "capabilities.yaml"
_DEFAULT_BACKUPS = ROOT / "panel" / "backups"
BACKUPS = _DEFAULT_BACKUPS

SECRET_FIELDS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("Tavily", ("TAVILY_API_KEY", "TAVILY"), "TAVILY_API_KEY"),
    ("Exa", ("EXA_API_KEY", "EXA"), "EXA_API_KEY"),
    ("Brave", ("BRAVE_API_KEY", "BRAVE"), "BRAVE_API_KEY"),
    ("SearXNG", ("SEARXNG_URL",), "SEARXNG_URL"),
    ("Firecrawl", ("FIRECRAWL_API_KEY", "FIRECRAWL"), "FIRECRAWL_API_KEY"),
    ("Jina", ("JINA_API_KEY", "JINA"), "JINA_API_KEY"),
    ("GitHub", ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_MCP_TOKEN"), "GITHUB_TOKEN"),
)

PROBES: dict[str, list[str]] = {
    "web_search": ["call", "web_search", "search", "--query", "python mcp", "--maxResults", "1"],
    "web_extract": ["call", "web_extract", "extract", "--url", "https://example.com"],
    "project_search": [
        "call",
        "project_search",
        "search",
        "--query",
        "octocat",
        "--maxResults",
        "1",
    ],
    "package_meta": ["call", "package_meta", "lookup", "--package", "pytest", "--ecosystem", "pypi"],
    "package_security": ["call", "package_security", "query", "--package", "requests", "--ecosystem", "PyPI"],
}

_WF_TOOL_MOD: Any = None


def _state_path() -> Path:
    if STATE != _DEFAULT_STATE:
        return STATE
    if os.environ.get("WF_DATA_DIR", "").strip() or os.environ.get("PLUGIN_DATA", "").strip():
        return wf_config.data_dir() / "panel-state.json"
    return STATE


def _backups_dir() -> Path:
    if BACKUPS != _DEFAULT_BACKUPS:
        return BACKUPS
    if os.environ.get("WF_DATA_DIR", "").strip() or os.environ.get("PLUGIN_DATA", "").strip():
        return wf_config.data_dir() / "prompt-backups"
    return BACKUPS


def _load_wf_tool() -> Any:
    global _WF_TOOL_MOD
    if _WF_TOOL_MOD is not None:
        return _WF_TOOL_MOD
    spec = importlib.util.spec_from_file_location("wf_tool_runtime", TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 wf-tool: {TOOL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _WF_TOOL_MOD = module
    return module


def _run_tool(args: list[str]) -> dict:
    wf = _load_wf_tool()
    if not args:
        raise RuntimeError("wf-tool 参数为空")
    cmd = args[0]
    if cmd == "list":
        return {"ok": True, "data": wf.list_capabilities(), "error": None, "degradation": [], "meta": {"ms": 0}}
    if cmd == "health":
        name = args[1] if len(args) > 1 and not args[1].startswith("--") else None
        return {"ok": True, "data": wf.health(name), "error": None, "degradation": [], "meta": {"ms": 0}}
    if cmd == "doctor":
        return {"ok": True, "data": wf.doctor(), "error": None, "degradation": [], "meta": {"ms": 0}}
    if cmd == "call":
        if len(args) < 3:
            raise RuntimeError("call 需要 <capability> <action>")
        payload = wf.parse_payload(args[3:])
        return wf.dispatch(args[1], args[2], payload)
    if cmd == "panel":
        mode = args[1][2:] if len(args) > 1 and args[1].startswith("--") else "status"
        if mode == "status":
            return {"ok": True, "data": wf._panel_status(), "error": None, "degradation": [], "meta": {"ms": 0}}
        if mode == "close":
            return {"ok": True, "data": wf._panel_close(), "error": None, "degradation": [], "meta": {"ms": 0}}
        return {"ok": True, "data": wf._panel_ensure(open_browser=False), "error": None, "degradation": [], "meta": {"ms": 0}}
    raise RuntimeError(f"不支持的 wf-tool 子命令: {cmd}")


def list_capabilities() -> dict:
    return _run_tool(["list"])["data"]


def health(name: str | None = None) -> dict:
    args = ["health"] + ([name] if name else [])
    return _run_tool(args)["data"]


def doctor() -> dict:
    return _run_tool(["doctor"])["data"]


def load_state() -> dict:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"disabled": []}
    if not isinstance(data, dict) or not isinstance(data.get("disabled"), list):
        return {"disabled": []}
    return data


def save_state(disabled: set[str]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"disabled": sorted(disabled)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_config() -> dict:
    return wf_config.load_config()


def save_config(data: dict) -> str:
    return str(wf_config.save_config(data))


def catalog_defaults() -> dict:
    data = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def masked_secrets() -> dict[str, dict]:
    data = load_config()
    secrets = data.get("secrets") or {}
    result: dict[str, dict] = {}
    for label, names, canonical in SECRET_FIELDS:
        value, actual, origin = wf_config.resolve_secret(*names)
        result[label] = {
            "present": bool(value),
            "masked": wf_config.mask(value),
            "source": origin,
            "actual": actual,
            "canonical": canonical,
            "envPresent": any(bool(os.environ.get(name)) for name in names),
            "configPresent": any(bool(secrets.get(name)) for name in names),
        }
    return result


def save_secret_updates(updates: dict[str, str], clears: set[str]) -> str:
    data = load_config()
    secrets = dict(data.get("secrets") or {})
    for label, value in updates.items():
        if value:
            for name, _, canonical in SECRET_FIELDS:
                if name == label:
                    secrets[canonical] = value
                    break
    for label in clears:
        for name, names, _ in SECRET_FIELDS:
            if name == label:
                for alias in names:
                    secrets.pop(alias, None)
                break
    data["secrets"] = secrets
    return save_config(data)


def save_provider_orders(orders: dict[str, list[str]]) -> str:
    caps = list_capabilities()["capabilities"]
    data = load_config()
    providers = dict(data.get("providers") or {})
    for name, chain in orders.items():
        declared = caps.get(name, {}).get("providers") or []
        cleaned = [item for item in chain if item]
        if not cleaned:
            providers.pop(name, None)
            continue
        unknown = [item for item in cleaned if item not in declared]
        if unknown:
            raise ValueError(f"{name} 包含未登记 provider: {', '.join(unknown)}")
        providers[name] = cleaned
    data["providers"] = providers
    return save_config(data)


def save_paths(runtime: dict[str, str], cli_paths: dict[str, dict[str, str]]) -> str:
    data = load_config()
    current_runtime = dict(data.get("runtime") or {})
    for key, value in runtime.items():
        if value:
            current_runtime[key] = value
        else:
            current_runtime.pop(key, None)
    data["runtime"] = current_runtime

    current_cli = dict(data.get("cli_paths") or {})
    for capability, mapping in cli_paths.items():
        target = dict(current_cli.get(capability) or {})
        for provider, value in mapping.items():
            if value:
                target[provider] = value
            else:
                target.pop(provider, None)
        if target:
            current_cli[capability] = target
        else:
            current_cli.pop(capability, None)
    data["cli_paths"] = current_cli
    return save_config(data)


def reset_paths() -> str:
    data = load_config()
    data.pop("runtime", None)
    data.pop("cli_paths", None)
    return save_config(data)


def probe(capability: str) -> dict:
    args = PROBES.get(capability)
    if args:
        return _run_tool(args)
    item = list_capabilities()["capabilities"].get(capability)
    if not item:
        return {"ok": False, "error": {"code": "UNKNOWN_CAPABILITY", "message": capability}}
    if item.get("kind") == "cli":
        return _run_tool(["health", capability])
    if item.get("kind") == "mcp":
        return {
            "ok": True,
            "data": {
                "note": "由宿主 MCP 提供，面板无法直接测试；请用 GitHub Token 的连通测试代替。",
                "provider": item.get("primary"),
            },
        }
    return _run_tool(["health", capability])


def session_info() -> dict[str, Any]:
    return wf_session.load_session()
