"""wf-tool：所有能力调用的唯一入口。

用法：
  python tools/wf-tool.py list
  python tools/wf-tool.py health [slot]
  python tools/wf-tool.py web_search search --query "..." --max-results 5
  python tools/wf-tool.py web_extract extract --url "https://..."
  python tools/wf-tool.py project_search search --query "searxng"
  python tools/wf-tool.py ledger commit --run-dir ".wf/runs/r1" --json "{...}"

返回值永远是统一信封；退出码 0=动作成功，1=动作失败。
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from tools.errors import ToolError  # noqa: E402
from tools.util import utc_now  # noqa: E402

CONTRACTS = ROOT / "contracts"
DEFAULT_REGISTRY = ROOT / "registry.yaml"
CORE_SLOTS = {"ledger", "render_prompt", "gates"}
BUILTIN_MODULES = {
    "ledger": ("tools.ledger", "tools.mocks.ledger"),
    "render_prompt": ("tools.render_prompt", "tools.mocks.render_prompt"),
    "gates": ("tools.gates", "tools.mocks.gates"),
}
MODULE_CACHE: dict[str, Any] = {}

NUMERIC_KEYS = {"maxResults", "max_results"}
KEY_ALIASES = {
    "max-results": "maxResults",
    "max_results": "maxResults",
    "run-dir": "run_dir",
    "prompt-blocks": "promptBlocks",
    "blocks-root": "blocksRoot",
}


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


def load_registry(path: str | Path | None = None) -> dict[str, Any]:
    registry_path = Path(path or os.environ.get("WF_REGISTRY") or DEFAULT_REGISTRY)
    try:
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolError("INTERNAL", f"registry 不存在: {registry_path}") from exc
    except yaml.YAMLError as exc:
        raise ToolError("INTERNAL", "registry.yaml 不是合法 YAML") from exc
    if not isinstance(data, dict):
        raise ToolError("INTERNAL", "registry.yaml 顶层必须是对象")
    _validate(data, "registry.schema.json")
    return data


def load_manifest(slot: str) -> dict[str, Any]:
    path = ROOT / "tools" / "adapters" / slot / "manifest.yaml"
    if not path.is_file():
        raise ToolError("UNKNOWN_SLOT", f"适配器 manifest 不存在: {slot}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ToolError("INTERNAL", f"{slot} manifest 不是合法 YAML") from exc
    if not isinstance(data, dict):
        raise ToolError("INTERNAL", f"{slot} manifest 顶层必须是对象")
    _validate(data, "adapter-manifest.schema.json")
    return data


def _load_adapter(slot: str) -> Any:
    key = f"adapter:{slot}"
    if key in MODULE_CACHE:
        return MODULE_CACHE[key]
    try:
        module = importlib.import_module(f"tools.adapters.{slot}.adapter")
    except ModuleNotFoundError as exc:
        raise ToolError("UNKNOWN_SLOT", f"没有适配器: {slot}") from exc
    MODULE_CACHE[key] = module
    return module


def _load_core(slot: str) -> Any:
    key = f"core:{slot}"
    if key in MODULE_CACHE:
        return MODULE_CACHE[key]
    last_missing: str | None = None
    for module_name in BUILTIN_MODULES[slot]:
        try:
            module = importlib.import_module(module_name)
            MODULE_CACHE[key] = module
            return module
        except ModuleNotFoundError as exc:
            last_missing = module_name
            if exc.name != module_name:
                raise
    raise ToolError("INTERNAL", f"核心槽模块缺失: {last_missing}")


def _envelope(
    *,
    ok: bool,
    slot: str,
    action: str,
    adapter: str,
    data: Any = None,
    error: dict[str, Any] | None = None,
    degradation: list[dict[str, Any]] | None = None,
    started: float,
    run_id: str | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {"ms": round((time.perf_counter() - started) * 1000, 1)}
    if run_id:
        meta["runId"] = run_id
    return {
        "ok": ok,
        "slot": slot,
        "action": action,
        "adapter": adapter,
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


def dispatch(
    slot: str,
    action: str,
    payload: dict[str, Any] | None = None,
    *,
    run_id: str | None = None,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    payload = payload or {}
    registry = registry or load_registry()

    if slot in CORE_SLOTS:
        module = _load_core(slot)
        try:
            data = module.handle(action, payload)
        except ToolError as exc:
            return _envelope(
                ok=False,
                slot=slot,
                action=action,
                adapter="internal",
                error=exc.to_dict(),
                started=started,
                run_id=run_id,
            )
        return _envelope(
            ok=True,
            slot=slot,
            action=action,
            adapter="internal",
            data=data,
            started=started,
            run_id=run_id,
        )

    slots = registry.get("slots") or {}
    entry = slots.get(slot)
    if not isinstance(entry, dict):
        return _envelope(
            ok=False,
            slot=slot,
            action=action,
            adapter="-",
            error=ToolError(
                "UNKNOWN_SLOT",
                f"registry 中没有槽: {slot}",
                details={"available": sorted(slots.keys())},
            ).to_dict(),
            started=started,
            run_id=run_id,
        )

    actions = entry.get("actions") or []
    if action not in actions:
        return _envelope(
            ok=False,
            slot=slot,
            action=action,
            adapter=str(entry.get("primary") or "-"),
            error=ToolError(
                "UNKNOWN_ACTION",
                f"{slot} 不支持动作: {action}",
                details={"actions": actions},
            ).to_dict(),
            started=started,
            run_id=run_id,
        )

    module = _load_adapter(slot)
    providers = _provider_chain(entry)
    if not providers:
        return _envelope(
            ok=False,
            slot=slot,
            action=action,
            adapter="-",
            error=ToolError("INTERNAL", f"{slot} 没有 provider").to_dict(),
            started=started,
            run_id=run_id,
        )

    degradation: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    last_error: ToolError | None = None
    last_provider = providers[-1]

    for index, provider in enumerate(providers):
        try:
            data = module.execute(action, payload, provider=provider)
            return _envelope(
                ok=True,
                slot=slot,
                action=action,
                adapter=provider,
                data=data,
                degradation=degradation,
                started=started,
                run_id=run_id,
            )
        except ToolError as exc:
            last_error = exc
            attempts.append({"provider": provider, "code": exc.code, "message": exc.message})
            if index + 1 >= len(providers) or not exc.allow_fallback:
                break
            next_provider = providers[index + 1]
            degradation.append(
                {
                    "slot": slot,
                    "from": provider,
                    "to": next_provider,
                    "reason": f"{exc.code}: {exc.message}",
                }
            )
        except Exception as exc:  # 未预期异常不静默降级
            last_error = ToolError(
                "INTERNAL",
                f"{slot} 适配器异常: {type(exc).__name__}",
                details={"provider": provider},
            )
            attempts.append({"provider": provider, "code": "INTERNAL", "message": type(exc).__name__})
            break

    if last_error is None:
        last_error = ToolError("INTERNAL", f"{slot} 未执行")
    if len(attempts) > 1:
        error = ToolError(
            "FALLBACK_EXHAUSTED",
            f"{slot} 主备均失败",
            retryable=last_error.retryable,
            details={"attempts": attempts},
        ).to_dict()
    else:
        error = last_error.to_dict()
        error.setdefault("details", {})["attempts"] = attempts
    return _envelope(
        ok=False,
        slot=slot,
        action=action,
        adapter=last_provider,
        error=error,
        degradation=degradation,
        started=started,
        run_id=run_id,
    )


def list_slots() -> dict[str, Any]:
    registry = load_registry()
    slots: dict[str, Any] = {}
    for slot, entry in (registry.get("slots") or {}).items():
        item = {
            "purpose": entry.get("purpose"),
            "actions": entry.get("actions"),
            "primary": entry.get("primary"),
            "alternate": entry.get("alternate"),
            "fallback": entry.get("fallback"),
            "status": entry.get("status"),
            "license": entry.get("license"),
        }
        if slot not in CORE_SLOTS:
            try:
                manifest = load_manifest(slot)
                item["manifest"] = {
                    "version": manifest.get("version"),
                    "providers": manifest.get("providers"),
                    "credentials": manifest.get("credentials"),
                }
            except ToolError as exc:
                item["manifestError"] = exc.message
        slots[slot] = item
    return {
        "registry": str(DEFAULT_REGISTRY),
        "slots": slots,
        "builtins": sorted(CORE_SLOTS - set(slots)),
        "checkedAt": utc_now(),
    }


def health(slot: str | None = None) -> dict[str, Any]:
    registry = load_registry()
    entries = registry.get("slots") or {}
    all_names = list(entries.keys()) + [name for name in sorted(CORE_SLOTS) if name not in entries]
    selected = [slot] if slot else all_names
    result: dict[str, Any] = {}
    degraded: list[str] = []
    missing: list[str] = []

    for name in selected:
        if name in CORE_SLOTS:
            try:
                _load_core(name)
                result[name] = {"status": "active", "adapter": "internal"}
            except ToolError as exc:
                result[name] = {"status": "missing", "reason": exc.message}
                missing.append(name)
            continue
        entry = entries.get(name)
        if not isinstance(entry, dict):
            result[name] = {"status": "missing", "reason": "registry 中没有该槽"}
            missing.append(name)
            continue
        try:
            module = _load_adapter(name)
        except ToolError as exc:
            result[name] = {"status": "missing", "reason": exc.message}
            missing.append(name)
            continue
        providers = _provider_chain(entry)
        checks: dict[str, Any] = {}
        for provider in providers:
            try:
                checks[provider] = module.health(provider)
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
        "slots": result,
        "degraded": degraded,
        "missing": missing,
    }


def _parse_scalar(value: str) -> Any:
    if value in {"true", "false"}:
        return value == "true"
    return value


def parse_payload(argv: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in {"--json", "--input"}:
            if i + 1 >= len(argv):
                raise ToolError("INVALID_INPUT", f"{token} 缺少值")
            raw = argv[i + 1]
            if raw == "-":
                raw = sys.stdin.read()
            elif token == "--input":
                raw = Path(raw).read_text(encoding="utf-8")
            try:
                parsed = json.loads(raw)
            except ValueError as exc:
                raise ToolError("INVALID_INPUT", f"{token} 不是合法 JSON") from exc
            if not isinstance(parsed, dict):
                raise ToolError("INVALID_INPUT", f"{token} 必须是 JSON 对象")
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
        if key == "names" and isinstance(value, str):
            value = [x.strip() for x in value.split(",") if x.strip()]
        elif key in {"blocks", "promptBlocks"} and isinstance(value, str):
            value = [x.strip() for x in value.split(",") if x.strip()]
        elif key in NUMERIC_KEYS:
            try:
                value = int(value)
            except (TypeError, ValueError) as exc:
                raise ToolError("INVALID_INPUT", f"{key} 必须是整数") from exc
        elif key in {"run", "evidence"} and isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError as exc:
                raise ToolError("INVALID_INPUT", f"{key} 必须是 JSON") from exc
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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help", "help"}:
        sys.stdout.buffer.write((__doc__ or "").encode("utf-8"))
        sys.stdout.buffer.flush()
        return 0
    try:
        if argv[0] == "list":
            return emit(
                {
                    "ok": True,
                    "data": list_slots(),
                    "error": None,
                    "degradation": [],
                    "meta": {"ms": 0},
                }
            )
        if argv[0] == "health":
            slot = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else None
            return emit(
                {
                    "ok": True,
                    "data": health(slot),
                    "error": None,
                    "degradation": [],
                    "meta": {"ms": 0},
                }
            )
        if len(argv) < 2:
            raise ToolError("INVALID_INPUT", "需要 <slot> <action>")
        slot, action = argv[0], argv[1]
        payload = parse_payload(argv[2:])
        return emit(dispatch(slot, action, payload, run_id=payload.get("run_id")))
    except ToolError as exc:
        return emit(
            {
                "ok": False,
                "slot": "-",
                "action": "-",
                "adapter": "-",
                "data": None,
                "error": exc.to_dict(),
                "degradation": [],
                "meta": {"ms": 0},
            }
        )


if __name__ == "__main__":
    raise SystemExit(main())
