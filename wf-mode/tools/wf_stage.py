"""分阶段只读包装器：用工具集差异实现硬闸口。

用法：
  python tools/wf_stage.py calibrate
  python tools/wf_stage.py research <capability> <action> [--key value | --json "{...}"]

`calibrate` 只做能力校准与面板启动；`research` 只放行已登记的只读能力。
写类、pending、未知能力一律拒绝。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "wf-tool.py"

READ_ACTIONS: dict[str, set[str]] = {
    "project_search": {"search", "lookup", "health"},
    "web_search": {"search", "health"},
    "web_extract": {"extract", "health"},
    "repo_ingest": {"ingest", "health"},
    "structural_search": {"search", "health"},
    "dependency_graph": {"graph", "health"},
}


class StageError(Exception):
    pass


def _run(args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = (proc.stdout or "").strip()
    if not text:
        raise StageError(f"wf-tool 没有输出；stderr: {(proc.stderr or '')[:400]}")
    try:
        return json.loads(text)
    except ValueError as exc:
        raise StageError(f"wf-tool 输出不是 JSON: {text[:200]}") from exc


def _emit(data: dict[str, Any], code: int = 0) -> int:
    sys.stdout.buffer.write(
        (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    sys.stdout.buffer.flush()
    return code


def calibrate() -> int:
    health = _run(["health"])
    doctor = _run(["doctor"])
    listed = _run(["list"])
    panel = _run(["panel", "--ensure"])

    statuses = health.get("data", {}).get("capabilities", {})
    buckets: dict[str, list[str]] = {
        "active": [],
        "degraded": [],
        "missing": [],
        "pending": [],
        "disabled": [],
    }
    for name, item in statuses.items():
        status = str(item.get("status") or "missing")
        buckets.setdefault(status, []).append(name)

    data = {
        "ok": bool(health.get("ok")) and bool(doctor.get("ok")),
        "runtime": doctor.get("data", {}).get("runtime", {}),
        "hosts": doctor.get("data", {}).get("hosts", {}),
        "capabilities": buckets,
        "sources": {
            name: item.get("envSources", {})
            for name, item in listed.get("data", {}).get("capabilities", {}).items()
            if item.get("envSources")
        },
        "panel": panel.get("data", {}),
    }
    return _emit(data, 0 if data["ok"] else 1)


def research(args: list[str]) -> int:
    if len(args) < 2:
        raise StageError("需要 research <capability> <action>")
    capability, action = args[0], args[1]
    allowed = READ_ACTIONS.get(capability)
    if not allowed:
        raise StageError(f"阶段 4 不允许调用能力: {capability}")
    if action not in allowed:
        raise StageError(f"{capability} 不允许动作: {action}")
    if ".." in " ".join(args):
        raise StageError("禁止路径穿越（..）")

    envelope = _run(["call", capability, action, *args[2:]])
    return _emit(envelope, 0 if envelope.get("ok") else 1)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help", "help"}:
        sys.stdout.buffer.write((__doc__ or "").encode("utf-8"))
        sys.stdout.buffer.flush()
        return 0
    try:
        command = args[0]
        if command == "calibrate":
            if len(args) > 1:
                raise StageError("calibrate 不接受额外参数")
            return calibrate()
        if command == "research":
            return research(args[1:])
        raise StageError(f"未知阶段命令: {command}")
    except StageError as exc:
        return _emit({"ok": False, "error": {"code": "STAGE_ERROR", "message": str(exc)}}, 1)


if __name__ == "__main__":
    raise SystemExit(main())
