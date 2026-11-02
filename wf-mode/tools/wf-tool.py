"""wf-tool：能力调用的唯一入口。

用法：
  python tools/wf-tool.py list
  python tools/wf-tool.py health [capability]
  python tools/wf-tool.py doctor
  python tools/wf-tool.py call <capability> <action> [--key value | --json "{...}"]
  python tools/wf-tool.py panel

返回值永远是统一信封；退出码 0=成功，1=失败。
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import URLError
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from tools import config as local_config  # noqa: E402
from tools.errors import ToolError  # noqa: E402
from tools.util import first_env, utc_now  # noqa: E402

CONTRACTS = ROOT / "contracts"
DEFAULT_CATALOG = ROOT / "capabilities.yaml"
DISABLED_STATE = ROOT / "panel" / "state.json"
PANEL_LOCK = ROOT / ".wf" / "panel.lock.json"
PANEL_LOG = ROOT / ".wf" / "logs" / "panel.log"
PANEL_BASE_PORT = 8765
PANEL_PORT_SPAN = 30
MODULE_CACHE: dict[str, Any] = {}

NUMERIC_KEYS = {"maxResults", "max_results"}
KEY_ALIASES = {"max-results": "maxResults", "max_results": "maxResults"}

def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _validate(obj: Any, schema_name: str) -> None:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return
    validator = Draft202012Validator(_load_schema(schema_name))
    errors = sorted(validator.iter_errors(obj), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        raise ToolError(
            "INTERNAL",
            f"{schema_name} 校验失败: {first.message}",
            details={"schema": schema_name},
        )


def load_catalog(path: str | Path | None = None) -> dict[str, Any]:
    catalog_path = Path(path or os.environ.get("WF_CATALOG") or DEFAULT_CATALOG)
    try:
        data = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolError("INTERNAL", f"能力目录不存在: {catalog_path}") from exc
    except yaml.YAMLError as exc:
        raise ToolError("INTERNAL", "capabilities.yaml 不是合法 YAML") from exc
    if not isinstance(data, dict):
        raise ToolError("INTERNAL", "capabilities.yaml 顶层必须是对象")
    _validate(data, "capability.schema.json")
    try:
        local_config.merge_catalog(data)
    except local_config.ConfigError as exc:
        raise ToolError("INTERNAL", f"本地配置无效: {exc}") from exc
    for name, entry in (data.get("capabilities") or {}).items():
        providers = entry.get("providers") or []
        primary = entry.get("primary")
        if primary not in providers:
            raise ToolError(
                "INTERNAL",
                f"{name} 的 primary 不在 providers 中",
                details={"primary": primary, "providers": providers},
            )
    return data


def load_manifest(capability: str) -> dict[str, Any]:
    path = ROOT / "tools" / "adapters" / capability / "manifest.yaml"
    if not path.is_file():
        raise ToolError("UNKNOWN_CAPABILITY", f"适配器 manifest 不存在: {capability}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ToolError("INTERNAL", f"{capability} manifest 不是合法 YAML") from exc
    if not isinstance(data, dict):
        raise ToolError("INTERNAL", f"{capability} manifest 顶层必须是对象")
    _validate(data, "adapter-manifest.schema.json")
    return data


def _load_adapter(capability: str) -> Any:
    key = f"adapter:{capability}"
    if key in MODULE_CACHE:
        return MODULE_CACHE[key]
    try:
        module = importlib.import_module(f"tools.adapters.{capability}.adapter")
    except ModuleNotFoundError as exc:
        raise ToolError("UNKNOWN_CAPABILITY", f"没有适配器: {capability}") from exc
    MODULE_CACHE[key] = module
    return module


def _load_cli_tool() -> Any:
    key = "cli_tool"
    if key in MODULE_CACHE:
        return MODULE_CACHE[key]
    module = importlib.import_module("tools.adapters.cli_tool")
    MODULE_CACHE[key] = module
    return module


def _disabled() -> set[str]:
    try:
        data = json.loads(DISABLED_STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return set()
    values = data.get("disabled") if isinstance(data, dict) else None
    if not isinstance(values, list):
        return set()
    return {str(v) for v in values}


def _runtime(catalog: dict[str, Any]) -> dict[str, str]:
    try:
        configured = local_config.load_config().get("runtime") or {}
    except local_config.ConfigError as exc:
        raise ToolError("INTERNAL", f"本地配置无效: {exc}") from exc
    runtime = catalog.get("runtime") or {}
    return {
        "bin": str(
            configured.get("bin") or os.environ.get("WF_BIN") or runtime.get("bin") or ""
        ),
        "venv": str(
            configured.get("venv") or os.environ.get("WF_VENV") or runtime.get("venv") or ""
        ),
    }


def _envelope(
    *,
    ok: bool,
    capability: str,
    action: str,
    provider: str,
    data: Any = None,
    error: dict[str, Any] | None = None,
    degradation: list[dict[str, Any]] | None = None,
    started: float,
    cached: bool | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {"ms": round((time.perf_counter() - started) * 1000, 1)}
    if cached is not None:
        meta["cached"] = bool(cached)
    return {
        "ok": ok,
        "capability": capability,
        "action": action,
        "provider": provider,
        "data": data,
        "error": error,
        "degradation": degradation or [],
        "meta": meta,
    }


def _provider_chain(entry: dict[str, Any]) -> list[str]:
    providers: list[str] = []
    for value in [entry.get("primary"), entry.get("alternate"), *(entry.get("fallback") or [])]:
        if isinstance(value, str) and value and value not in providers:
            providers.append(value)
    return providers


def _run_provider(
    kind: str,
    capability: str,
    entry: dict[str, Any],
    action: str,
    payload: dict[str, Any],
    provider: str,
    runtime: dict[str, str],
) -> dict[str, Any]:
    if kind == "adapter":
        module = _load_adapter(capability)
        return module.execute(action, payload, provider=provider)
    if kind == "cli":
        return _load_cli_tool().execute(action, payload, provider, entry, runtime)
    raise ToolError("INTERNAL", f"未知能力类型: {kind}")


def _mcp_data(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "mcp",
        "server": entry.get("mcp_server"),
        "tools": entry.get("mcp_tools") or [],
        "note": "由宿主 MCP 提供；实际调用由 agent 直接使用对应 MCP 工具，wf-tool 只报告接入状态。",
    }


def dispatch(
    capability: str,
    action: str,
    payload: dict[str, Any] | None = None,
    *,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    payload = dict(payload or {})
    forced_provider = payload.pop("provider", None)
    catalog = catalog or load_catalog()
    entries = catalog.get("capabilities") or {}
    entry = entries.get(capability)

    if not isinstance(entry, dict):
        return _envelope(
            ok=False,
            capability=capability,
            action=action,
            provider="-",
            error=ToolError(
                "UNKNOWN_CAPABILITY",
                f"能力目录中没有: {capability}",
                details={"available": sorted(entries.keys())},
            ).to_dict(),
            started=started,
        )

    if capability in _disabled():
        return _envelope(
            ok=False,
            capability=capability,
            action=action,
            provider=str(entry.get("primary") or "-"),
            error=ToolError(
                "CAPABILITY_DISABLED",
                f"{capability} 已在面板中停用",
                details={"state": str(DISABLED_STATE)},
            ).to_dict(),
            started=started,
        )

    actions = entry.get("actions") or []
    if action not in actions:
        return _envelope(
            ok=False,
            capability=capability,
            action=action,
            provider=str(entry.get("primary") or "-"),
            error=ToolError(
                "UNKNOWN_ACTION",
                f"{capability} 不支持动作: {action}",
                details={"actions": actions},
            ).to_dict(),
            started=started,
        )

    kind = str(entry.get("kind") or "")
    if kind == "pending":
        return _envelope(
            ok=False,
            capability=capability,
            action=action,
            provider=str(entry.get("primary") or "-"),
            error=ToolError(
                "CAPABILITY_PENDING",
                f"{capability} 尚未接入，不能调用",
                details={"notes": entry.get("notes") or ""},
            ).to_dict(),
            started=started,
        )

    if kind == "mcp":
        return _envelope(
            ok=True,
            capability=capability,
            action=action,
            provider=str(entry.get("primary") or "mcp"),
            data=_mcp_data(entry),
            started=started,
        )

    runtime = _runtime(catalog)
    providers = _provider_chain(entry)
    if not providers:
        return _envelope(
            ok=False,
            capability=capability,
            action=action,
            provider="-",
            error=ToolError("INTERNAL", f"{capability} 没有 provider").to_dict(),
            started=started,
        )
    if forced_provider:
        if forced_provider not in providers:
            return _envelope(
                ok=False,
                capability=capability,
                action=action,
                provider=str(forced_provider),
                error=ToolError(
                    "INVALID_INPUT",
                    f"{capability} 不支持 provider: {forced_provider}",
                    details={"providers": providers},
                ).to_dict(),
                started=started,
            )
        providers = [forced_provider]

    degradation: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    last_error: ToolError | None = None
    last_provider = providers[-1]

    for index, provider in enumerate(providers):
        try:
            data = _run_provider(kind, capability, entry, action, payload, provider, runtime)
            cached = data.pop("_cached", None) if isinstance(data, dict) else None
            return _envelope(
                ok=True,
                capability=capability,
                action=action,
                provider=provider,
                data=data,
                degradation=degradation,
                started=started,
                cached=bool(cached) if cached is not None else None,
            )
        except ToolError as exc:
            last_error = exc
            attempts.append({"provider": provider, "code": exc.code, "message": exc.message})
            if index + 1 >= len(providers) or not exc.allow_fallback:
                break
            next_provider = providers[index + 1]
            degradation.append(
                {
                    "capability": capability,
                    "from": provider,
                    "to": next_provider,
                    "reason": f"{exc.code}: {exc.message}",
                }
            )
        except Exception as exc:  # 未预期异常不静默降级
            last_error = ToolError(
                "INTERNAL",
                f"{capability} 执行异常: {type(exc).__name__}",
                details={"provider": provider},
            )
            attempts.append({"provider": provider, "code": "INTERNAL", "message": type(exc).__name__})
            break

    if last_error is None:
        last_error = ToolError("INTERNAL", f"{capability} 未执行")
    if len(attempts) > 1:
        error = ToolError(
            "FALLBACK_EXHAUSTED",
            f"{capability} 主备均失败",
            retryable=last_error.retryable,
            details={"attempts": attempts},
        ).to_dict()
    else:
        error = last_error.to_dict()
        error.setdefault("details", {})["attempts"] = attempts
    return _envelope(
        ok=False,
        capability=capability,
        action=action,
        provider=last_provider,
        error=error,
        degradation=degradation,
        started=started,
    )


def _env_presence(entry: dict[str, Any]) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for name in entry.get("env") or []:
        try:
            value, _, _ = local_config.resolve_secret(name)
        except local_config.ConfigError as exc:
            raise ToolError("INTERNAL", f"本地配置无效: {exc}") from exc
        result[name] = bool(value)
    return result


def _env_sources(entry: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in entry.get("env") or []:
        try:
            _, _, origin = local_config.resolve_secret(name)
        except local_config.ConfigError as exc:
            raise ToolError("INTERNAL", f"本地配置无效: {exc}") from exc
        result[name] = origin
    return result


def _cli_binary(capability: str, entry: dict[str, Any], runtime: dict[str, str]) -> str:
    exec_map = entry.get("exec") or {}
    primary = entry.get("primary")
    argv = exec_map.get(primary) or []
    if not argv:
        return ""
    binary = str(argv[0]).replace("{WF_BIN}", runtime["bin"]).replace("{WF_VENV}", runtime["venv"])
    return binary


def list_capabilities() -> dict[str, Any]:
    catalog = load_catalog()
    runtime = _runtime(catalog)
    disabled = _disabled()
    items: dict[str, Any] = {}
    for name, entry in (catalog.get("capabilities") or {}).items():
        item: dict[str, Any] = {
            "enabled": name not in disabled,
            "label": entry.get("label"),
            "kind": entry.get("kind"),
            "actions": entry.get("actions"),
            "providers": entry.get("providers") or [],
            "primary": entry.get("primary"),
            "alternate": entry.get("alternate"),
            "fallback": entry.get("fallback"),
            "status": entry.get("status"),
            "env": _env_presence(entry),
            "envSources": _env_sources(entry),
            "notes": entry.get("notes") or "",
        }
        kind = entry.get("kind")
        if kind == "adapter":
            try:
                manifest = load_manifest(name)
                item["manifest"] = {
                    "version": manifest.get("version"),
                    "providers": manifest.get("providers"),
                }
            except ToolError as exc:
                item["manifestError"] = exc.message
        elif kind == "cli":
            binary = _cli_binary(name, entry, runtime)
            item["command"] = binary
            item["commandExists"] = bool(binary) and os.path.isfile(binary)
        elif kind == "mcp":
            item["mcpServer"] = entry.get("mcp_server")
            item["mcpTools"] = entry.get("mcp_tools") or []
        items[name] = item
    return {
        "catalog": str(DEFAULT_CATALOG),
        "runtime": runtime,
        "capabilities": items,
        "checkedAt": utc_now(),
    }


def health(capability: str | None = None) -> dict[str, Any]:
    catalog = load_catalog()
    runtime = _runtime(catalog)
    entries = catalog.get("capabilities") or {}
    selected = [capability] if capability else list(entries.keys())
    result: dict[str, Any] = {}
    degraded: list[str] = []
    missing: list[str] = []
    pending: list[str] = []

    for name in selected:
        entry = entries.get(name)
        if not isinstance(entry, dict):
            result[name] = {"status": "missing", "reason": "能力目录中没有该项"}
            missing.append(name)
            continue

        if name in _disabled():
            result[name] = {"status": "disabled", "reason": "面板中已停用"}
            continue

        kind = entry.get("kind")
        if entry.get("status") == "pending" or kind == "pending":
            result[name] = {
                "status": "pending",
                "reason": entry.get("notes") or "尚未接入",
            }
            pending.append(name)
            continue

        if kind == "mcp":
            result[name] = {
                "status": "active",
                "provider": entry.get("primary"),
                "external": True,
                "server": entry.get("mcp_server"),
                "tools": entry.get("mcp_tools") or [],
            }
            continue

        checks: dict[str, Any] = {}
        for provider in _provider_chain(entry):
            try:
                if kind == "adapter":
                    checks[provider] = _load_adapter(name).health(provider)
                elif kind == "cli":
                    checks[provider] = _load_cli_tool().health(entry, provider, runtime)
                else:
                    checks[provider] = {"ok": False, "reason": f"未知类型: {kind}"}
            except ToolError as exc:
                checks[provider] = {"ok": False, "provider": provider, "error": exc.to_dict()}

        primary = entry.get("primary")
        primary_ok = bool(checks.get(primary, {}).get("ok"))
        any_ok = any(bool(v.get("ok")) for v in checks.values())
        status = "active" if primary_ok else ("degraded" if any_ok else "missing")
        if status == "degraded":
            degraded.append(name)
        if status == "missing":
            missing.append(name)
        result[name] = {"status": status, "providers": checks}

    return {
        "checkedAt": utc_now(),
        "capabilities": result,
        "degraded": degraded,
        "missing": missing,
        "pending": pending,
    }


def doctor() -> dict[str, Any]:
    catalog = load_catalog()
    runtime = _runtime(catalog)
    capabilities: dict[str, Any] = {}
    for name, entry in (catalog.get("capabilities") or {}).items():
        kind = entry.get("kind")
        item: dict[str, Any] = {
            "kind": kind,
            "status": entry.get("status"),
            "env": _env_presence(entry),
            "envSources": _env_sources(entry),
        }
        if kind == "cli":
            binary = _cli_binary(name, entry, runtime)
            item["command"] = binary
            item["commandExists"] = bool(binary) and os.path.isfile(binary)
        elif kind == "adapter":
            item["manifestExists"] = (ROOT / "tools" / "adapters" / name / "manifest.yaml").is_file()
        elif kind == "mcp":
            item["mcpServer"] = entry.get("mcp_server")
            item["mcpTools"] = entry.get("mcp_tools") or []
        elif kind == "pending":
            item["notes"] = entry.get("notes") or ""
        capabilities[name] = item

    haha_path = local_config.resolve_haha_sidecar()
    hosts = {
        "haha": {"detected": Path(haha_path).is_file(), "path": haha_path},
        "claude": {"detected": bool(shutil.which("claude")), "path": shutil.which("claude") or ""},
        "dsh": {"detected": bool(shutil.which("dsh") or shutil.which("dsh-next")), "path": shutil.which("dsh") or shutil.which("dsh-next") or ""},
    }

    return {
        "checkedAt": utc_now(),
        "runtime": {
            "bin": runtime["bin"],
            "binExists": bool(runtime["bin"]) and Path(runtime["bin"]).is_dir(),
            "venv": runtime["venv"],
            "venvExists": bool(runtime["venv"]) and Path(runtime["venv"]).is_dir(),
        },
        "capabilities": capabilities,
        "hosts": hosts,
    }


def _parse_scalar(value: str) -> Any:
    if value in {"true", "false"}:
        return value == "true"
    if value in {"null", "none"}:
        return None
    return value


def parse_payload(argv: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--json":
            if i + 1 >= len(argv):
                raise ToolError("INVALID_INPUT", "--json 缺少值")
            raw = argv[i + 1]
            if raw == "-":
                raw = sys.stdin.read()
            try:
                parsed = json.loads(raw)
            except ValueError as exc:
                raise ToolError("INVALID_INPUT", "--json 不是合法 JSON") from exc
            if not isinstance(parsed, dict):
                raise ToolError("INVALID_INPUT", "--json 必须是 JSON 对象")
            payload.update(parsed)
            i += 2
            continue
        if not token.startswith("--"):
            raise ToolError("INVALID_INPUT", f"无法解析参数: {token}")
        key = token[2:]
        if "=" in key:
            key, value = key.split("=", 1)
        else:
            if i + 1 >= len(argv):
                payload[key] = True
                i += 1
                continue
            value = argv[i + 1]
            i += 1
        key = KEY_ALIASES.get(key, key)
        value = _parse_scalar(value)
        if key in NUMERIC_KEYS:
            try:
                value = int(value)
            except (TypeError, ValueError) as exc:
                raise ToolError("INVALID_INPUT", f"{key} 必须是整数") from exc
        payload[key] = value
        i += 1
    return payload


def emit(envelope: dict[str, Any]) -> int:
    # 直接写 UTF-8 字节，避免 Windows 控制台默认编码把中文变成乱码。
    sys.stdout.buffer.write(
        (json.dumps(envelope, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    sys.stdout.buffer.flush()
    return 0 if envelope.get("ok") else 1


def _emit_data(data: Any) -> int:
    return emit(
        {
            "ok": True,
            "data": data,
            "error": None,
            "degradation": [],
            "meta": {"ms": 0},
        }
    )


def _panel_health(port: int, timeout: float = 0.8) -> bool:
    if not port:
        return False
    try:
        with urlrequest.urlopen(
            f"http://127.0.0.1:{port}/_stcore/health", timeout=timeout
        ) as response:
            return int(getattr(response, "status", 0)) == 200
    except (URLError, OSError, ValueError):
        return False


def _read_panel_lock() -> dict[str, Any]:
    try:
        data = json.loads(PANEL_LOCK.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_panel_lock(data: dict[str, Any]) -> None:
    PANEL_LOCK.parent.mkdir(parents=True, exist_ok=True)
    temp = PANEL_LOCK.with_name(PANEL_LOCK.name + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp, PANEL_LOCK)


def _free_port(preferred: int) -> int:
    for port in range(preferred, preferred + PANEL_PORT_SPAN):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    return 0


def _panel_status() -> dict[str, Any]:
    lock = _read_panel_lock()
    try:
        port = int(lock.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    running = _panel_health(port)
    return {
        "running": running,
        "already_running": running,
        "port": port,
        "url": lock.get("url") or (f"http://127.0.0.1:{port}" if port else ""),
        "pid": lock.get("pid"),
        "startedAt": lock.get("startedAt"),
    }


def _open_panel(url: str) -> bool:
    if not url:
        return False
    try:
        return bool(webbrowser.open(url, new=2))
    except (OSError, webbrowser.Error):
        return False


def _panel_ensure() -> dict[str, Any]:
    status = _panel_status()
    if status["running"]:
        status["opened"] = _open_panel(status.get("url") or "")
        return status

    catalog = load_catalog()
    runtime = _runtime(catalog)
    streamlit = Path(runtime["venv"]) / "Scripts" / "streamlit.exe"
    if not streamlit.is_file():
        found = shutil.which("streamlit")
        if not found:
            raise ToolError("TOOL_MISSING", "找不到 streamlit，请先安装或设置 WF_VENV")
        streamlit = Path(found)

    try:
        preferred = int(
            (local_config.load_config().get("panel") or {}).get("port")
            or PANEL_BASE_PORT
        )
    except (local_config.ConfigError, TypeError, ValueError):
        preferred = PANEL_BASE_PORT
    port = _free_port(preferred)
    if not port:
        return {
            "running": False,
            "started": False,
            "degraded": True,
            "reason": f"{preferred}–{preferred + PANEL_PORT_SPAN - 1} 没有可用端口",
        }

    PANEL_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = open(PANEL_LOG, "ab")
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    try:
        try:
            proc = subprocess.Popen(
                [
                    str(streamlit),
                    "run",
                    str(ROOT / "panel" / "app.py"),
                    "--server.address",
                    "127.0.0.1",
                    "--server.headless",
                    "true",
                    "--server.port",
                    str(port),
                    "--browser.gatherUsageStats",
                    "false",
                ],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                **kwargs,
            )
        except OSError as exc:
            return {
                "running": False,
                "started": False,
                "degraded": True,
                "reason": local_config.redact(f"启动面板失败: {type(exc).__name__}"),
            }
    finally:
        log.close()

    deadline = time.time() + 8
    while time.time() < deadline:
        if _panel_health(port, timeout=0.5):
            now = utc_now()
            data = {
                "running": True,
                "started": True,
                "already_running": False,
                "port": port,
                "url": f"http://127.0.0.1:{port}",
                "pid": proc.pid,
                "startedAt": now,
            }
            _write_panel_lock(data)
            data["opened"] = _open_panel(data["url"])
            return data
        time.sleep(0.4)

    try:
        proc.terminate()
    except OSError:
        pass
    tail = ""
    try:
        tail = local_config.redact(
            PANEL_LOG.read_text(encoding="utf-8", errors="replace")[-800:]
        )
    except OSError:
        pass
    return {
        "running": False,
        "started": False,
        "degraded": True,
        "reason": "面板未在 8 秒内就绪",
        "logTail": tail,
    }


def _panel(mode: str = "ensure") -> int:
    if mode == "status":
        return _emit_data(_panel_status())
    if mode == "ensure":
        return _emit_data(_panel_ensure())
    raise ToolError("INVALID_INPUT", f"panel 不支持模式: {mode}")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help", "help"}:
        sys.stdout.buffer.write((__doc__ or "").encode("utf-8"))
        sys.stdout.buffer.flush()
        return 0
    try:
        command = argv[0]
        if command == "list":
            return _emit_data(list_capabilities())
        if command == "health":
            name = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else None
            return _emit_data(health(name))
        if command == "doctor":
            return _emit_data(doctor())
        if command == "panel":
            mode = "ensure"
            if len(argv) > 1 and argv[1].startswith("--"):
                mode = argv[1][2:]
            return _panel(mode)
        if command == "call":
            if len(argv) < 3:
                raise ToolError("INVALID_INPUT", "需要 call <capability> <action>")
            capability, action = argv[1], argv[2]
            payload = parse_payload(argv[3:])
            return emit(dispatch(capability, action, payload))
        # 兼容旧式：<capability> <action>
        if len(argv) >= 2:
            capability, action = argv[0], argv[1]
            payload = parse_payload(argv[2:])
            return emit(dispatch(capability, action, payload))
        raise ToolError("INVALID_INPUT", "未知命令")
    except ToolError as exc:
        return emit(
            {
                "ok": False,
                "capability": "-",
                "action": "-",
                "provider": "-",
                "data": None,
                "error": exc.to_dict(),
                "degradation": [],
                "meta": {"ms": 0},
            }
        )


if __name__ == "__main__":
    raise SystemExit(main())
