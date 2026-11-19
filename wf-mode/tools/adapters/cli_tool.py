"""通用 CLI 适配器：按能力目录的 exec 模板执行本地工具。

约束：
- 只接受 argv 数组，不经过 shell；
- 跨平台自动回退探测：cli_paths > WF_BIN/WF_VENV (Windows Scripts/*.exe / POSIX bin/*) > PATH；
- 只替换声明的占位符；
- 超时、非零退出、不可解析输出都显式报错；
- 输出统一归一化为 JSON 或文本。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tools import config as local_config
from tools.errors import ToolError
from tools.util import utc_now

DEFAULT_TIMEOUT = 60
MAX_TEXT = 20000

PLACEHOLDER_KEYS = {
    "path": "path",
    "repo": "repo",
    "pattern": "pattern",
    "lang": "lang",
    "url": "url",
    "query": "query",
    "maxResults": "maxResults",
    "template": "template",
    "destination": "destination",
}
DEFAULTS = {"path": ".", "lang": "python", "maxResults": 5}


def _runtime(entry: dict[str, Any], runtime: dict[str, Any] | None) -> dict[str, str]:
    runtime = runtime or {}
    return {
        "WF_BIN": str(runtime.get("bin") or os.environ.get("WF_BIN") or ""),
        "WF_VENV": str(runtime.get("venv") or os.environ.get("WF_VENV") or ""),
    }


def _subprocess_env(entry: dict[str, Any]) -> dict[str, str]:
    """只向子进程补充该能力声明的密钥，不注入全部面板密钥。"""
    env = dict(os.environ)
    for name in entry.get("env") or []:
        try:
            value, _, _ = local_config.resolve_secret(name)
        except local_config.ConfigError:
            continue
        if value:
            env[name] = value
    return env


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return local_config.redact(value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value


def _template(entry: dict[str, Any], provider: str) -> list[str]:
    exec_map = entry.get("exec") or {}
    argv = exec_map.get(provider)
    if not isinstance(argv, list) or not argv:
        raise ToolError(
            "UNKNOWN_PROVIDER",
            f"{entry.get('label')} 没有 provider 的执行模板: {provider}",
            details={"providers": sorted(exec_map.keys())},
        )
    return [str(item) for item in argv]


def resolve_binary(template_cmd: str, provider: str, runtime: dict[str, str]) -> str:
    """解析 CLI 可执行文件，兼顾 Windows/Linux/macOS 与 PATH 回退。"""
    raw = template_cmd.replace("{WF_BIN}", runtime["WF_BIN"]).replace("{WF_VENV}", runtime["WF_VENV"])
    if raw and os.path.isfile(raw):
        return raw

    stem = Path(raw).stem if raw else provider
    candidates: list[Path] = []
    if runtime["WF_VENV"]:
        venv = Path(runtime["WF_VENV"])
        candidates.extend([venv / "Scripts" / f"{stem}.exe", venv / "Scripts" / stem, venv / "bin" / stem])
    if runtime["WF_BIN"]:
        bindir = Path(runtime["WF_BIN"])
        candidates.extend([bindir / f"{stem}.exe", bindir / stem, bindir / stem / f"{stem}.exe", bindir / stem / stem])
    for cand in candidates:
        if cand.is_file():
            return str(cand)

    found = shutil.which(stem) or (shutil.which(provider) if provider != stem else None)
    if found:
        return found
    return raw


def _render(
    argv: list[str],
    payload: dict[str, Any],
    runtime: dict[str, str],
    provider: str,
) -> list[str]:
    values: dict[str, str] = dict(runtime)
    joined = " ".join(argv)
    for key, payload_key in PLACEHOLDER_KEYS.items():
        if "{" + key + "}" not in joined:
            continue
        value = payload.get(payload_key)
        if value is None:
            value = DEFAULTS.get(key)
        if value is None:
            raise ToolError(
                "INVALID_INPUT",
                f"缺少参数: {payload_key}",
                details={"expected": f"--{payload_key}"},
            )
        values[key] = str(value)

    known = set(values) | set(PLACEHOLDER_KEYS)
    rendered: list[str] = []
    for idx, item in enumerate(argv):
        if idx == 0:
            rendered.append(resolve_binary(item, provider, runtime))
            continue
        out = item
        for key, value in values.items():
            out = out.replace("{" + key + "}", value)
        for key in known:
            if "{" + key + "}" in out:
                raise ToolError("INVALID_INPUT", f"exec 模板占位符未解析: {item}")
        rendered.append(out)
    return rendered


def _normalize(action: str, provider: str, command: list[str], stdout: str, stderr: str) -> dict[str, Any]:
    text = stdout.strip()
    data: Any = None
    fmt = "text"
    if text:
        try:
            data = json.loads(text)
            fmt = "json"
        except ValueError:
            data = text[:MAX_TEXT]
    return {
        "ok": True,
        "provider": provider,
        "action": action,
        "command": command,
        "format": fmt,
        "data": data,
        "stderr": stderr.strip()[:MAX_TEXT],
        "checkedAt": utc_now(),
    }


def health(entry: dict[str, Any], provider: str, runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    argv = _template(entry, provider)
    rt = _runtime(entry, runtime)
    binary = resolve_binary(argv[0], provider, rt)
    exists = bool(binary) and os.path.isfile(binary)
    return {
        "ok": exists,
        "provider": provider,
        "command": binary,
        "exists": exists,
        "configured": exists,
        "checkedAt": utc_now(),
    }


def execute(
    action: str,
    payload: dict[str, Any],
    provider: str,
    capability: dict[str, Any],
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if action == "health":
        return health(capability, provider, runtime)

    rt = _runtime(capability, runtime)
    argv = _render(_template(capability, provider), payload, rt, provider)
    try:
        timeout = float(payload.get("timeout") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError) as exc:
        raise ToolError("INVALID_INPUT", "timeout 必须是数字") from exc
    if timeout <= 0 or timeout > 600:
        raise ToolError("INVALID_INPUT", "timeout 必须在 0–600 秒之间")

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            env=_subprocess_env(capability),
        )
    except FileNotFoundError as exc:
        raise ToolError(
            "TOOL_MISSING",
            f"命令不存在: {argv[0]}",
            details={"provider": provider},
            allow_fallback=True,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(
            "TIMEOUT",
            f"{entry_label(capability)} 执行超时: {timeout}s",
            details={"provider": provider},
            allow_fallback=True,
        ) from exc
    except OSError as exc:
        raise ToolError(
            "INTERNAL",
            f"启动命令失败: {type(exc).__name__}",
            details={"provider": provider},
            allow_fallback=True,
        ) from exc

    stdout = local_config.redact(proc.stdout or "")
    stderr = local_config.redact(proc.stderr or "")
    if proc.returncode != 0:
        raise ToolError(
            "UPSTREAM_ERROR",
            f"{entry_label(capability)} 退出码 {proc.returncode}",
            details={
                "provider": provider,
                "stderr": stderr.strip()[:2000],
                "stdout": stdout.strip()[:2000],
            },
            allow_fallback=True,
        )
    return _normalize(action, provider, _redact(argv), stdout, stderr)


def entry_label(entry: dict[str, Any]) -> str:
    return str(entry.get("label") or "cli")
