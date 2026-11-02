"""面板数据层：调用 wf-tool、读写提示词、启停与本地配置。

只做数据转换与最小 IO；不执行业务逻辑，不记录运行历史。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from tools import config as wf_config  # noqa: E402

TOOL = ROOT / "tools" / "wf-tool.py"
AGENT = ROOT / "agent" / "wf-agent.md"
STATE = ROOT / "panel" / "state.json"
CATALOG = ROOT / "capabilities.yaml"
BACKUPS = ROOT / "panel" / "backups"

SECRET_FIELDS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("Tavily", ("TAVILY_API_KEY", "TAVILY"), "TAVILY_API_KEY"),
    ("Exa", ("EXA_API_KEY", "EXA"), "EXA_API_KEY"),
    ("Firecrawl", ("FIRECRAWL_API_KEY", "FIRECRAWL"), "FIRECRAWL_API_KEY"),
    ("Jina", ("JINA_API_KEY", "JINA"), "JINA_API_KEY"),
    ("GitHub", ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_MCP_TOKEN"), "GITHUB_TOKEN"),
)

PROBES: dict[str, list[str]] = {
    "web_search": ["call", "web_search", "search", "--query", "ping", "--maxResults", "1"],
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
}


def _run_tool(args: list[str]) -> dict:
    proc = subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = wf_config.redact((proc.stdout or "").strip())
    if not text:
        stderr = wf_config.redact((proc.stderr or "").strip()[:500])
        raise RuntimeError(f"wf-tool 没有输出；stderr: {stderr}")
    return json.loads(text)


def list_capabilities() -> dict:
    return _run_tool(["list"])["data"]


def health(name: str | None = None) -> dict:
    args = ["health"] + ([name] if name else [])
    return _run_tool(args)["data"]


def doctor() -> dict:
    return _run_tool(["doctor"])["data"]


def load_state() -> dict:
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"disabled": []}
    if not isinstance(data, dict) or not isinstance(data.get("disabled"), list):
        return {"disabled": []}
    return data


def save_state(disabled: set[str]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
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
            for name, names, canonical in SECRET_FIELDS:
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


def split_agent() -> tuple[str, str]:
    text = AGENT.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[1].strip(), parts[2].lstrip("\n")
    return "", text


def agent_summary() -> dict:
    frontmatter, body = split_agent()
    tools = ""
    hook = ""
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if stripped.startswith("tools:"):
            tools = stripped.split(":", 1)[1].strip()
        if "wf_agent_gate.py" in stripped:
            hook = stripped
    return {"frontmatter": frontmatter, "body": body, "tools": tools, "hook": hook}


def save_agent_body(body: str) -> str:
    frontmatter, _ = split_agent()
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUPS / f"wf-agent-{stamp}.md"
    backup.write_text(AGENT.read_text(encoding="utf-8"), encoding="utf-8")
    AGENT.write_text(f"---\n{frontmatter}\n---\n\n{body.rstrip()}\n", encoding="utf-8")
    return str(backup)
