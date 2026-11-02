"""本地配置：面板保存的密钥、provider 顺序与工具路径。

优先级：本地配置 > 环境变量 > capabilities.yaml。
只负责读取、合并与原子写入；密钥不打印、不写日志。
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / ".wf" / "config.local.json"
BACKUP_DIR = ROOT / ".wf" / "backups"

SECRET_ENV_NAMES = (
    "TAVILY_API_KEY",
    "TAVILY",
    "EXA_API_KEY",
    "EXA",
    "FIRECRAWL_API_KEY",
    "FIRECRAWL",
    "JINA_API_KEY",
    "JINA",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_MCP_TOKEN",
)


class ConfigError(Exception):
    """本地配置不合法或无法读取。"""


def config_path(path: str | Path | None = None) -> Path:
    return Path(path or os.environ.get("WF_CONFIG") or DEFAULT_PATH)


def _validate(data: dict[str, Any]) -> None:
    version = data.get("version")
    if version is not None and version != 1:
        raise ConfigError(f"不支持的配置版本: {version}")

    runtime = data.get("runtime")
    if runtime is not None:
        if not isinstance(runtime, dict):
            raise ConfigError("runtime 必须是对象")
        for key in ("bin", "venv"):
            value = runtime.get(key)
            if value is not None and not isinstance(value, str):
                raise ConfigError(f"runtime.{key} 必须是字符串")

    providers = data.get("providers")
    if providers is not None:
        if not isinstance(providers, dict):
            raise ConfigError("providers 必须是对象")
        for name, chain in providers.items():
            if not isinstance(chain, list) or not chain:
                raise ConfigError(f"providers.{name} 必须是非空数组")
            if not all(isinstance(item, str) and item for item in chain):
                raise ConfigError(f"providers.{name} 只能包含非空字符串")

    cli_paths = data.get("cli_paths")
    if cli_paths is not None:
        if not isinstance(cli_paths, dict):
            raise ConfigError("cli_paths 必须是对象")
        for name, mapping in cli_paths.items():
            if not isinstance(mapping, dict):
                raise ConfigError(f"cli_paths.{name} 必须是对象")
            for provider, value in mapping.items():
                if not isinstance(value, str):
                    raise ConfigError(f"cli_paths.{name}.{provider} 必须是字符串")

    secrets = data.get("secrets")
    if secrets is not None:
        if not isinstance(secrets, dict):
            raise ConfigError("secrets 必须是对象")
        for name, value in secrets.items():
            if not isinstance(value, str):
                raise ConfigError(f"secrets.{name} 必须是字符串")

    panel = data.get("panel")
    if panel is not None:
        if not isinstance(panel, dict):
            raise ConfigError("panel 必须是对象")
        port = panel.get("port")
        if port is not None and (not isinstance(port, int) or not 1024 <= port <= 65535):
            raise ConfigError("panel.port 必须是 1024–65535 的整数")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    target = config_path(path)
    if not target.is_file():
        return {"version": 1}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"无法读取本地配置: {target}: {exc}") from exc
    except ValueError as exc:
        raise ConfigError(f"本地配置不是合法 JSON: {target}") from exc
    if not isinstance(data, dict):
        raise ConfigError("本地配置顶层必须是对象")
    _validate(data)
    return data


def resolve_secret(*names: str) -> tuple[str | None, str, str]:
    """按名称顺序解析密钥，返回 (值, 实际名称, 来源)。

    来源：panel（本地配置）/ env（环境变量）/ none。
    配置优先于环境变量，保证面板保存后立即生效。
    """
    data = load_config()
    secrets = data.get("secrets") or {}
    for name in names:
        value = secrets.get(name)
        if value:
            return value, name, "panel"
    for name in names:
        value = os.environ.get(name)
        if value:
            return value, name, "env"
    return None, names[0] if names else "", "none"


def resolve_credentials_candidates() -> list[Path]:
    """凭据文件候选顺序：WF_CREDENTIALS > 本地配置 credentials > 用户默认目录。"""
    candidates: list[Path] = []
    raw = os.environ.get("WF_CREDENTIALS")
    if raw:
        candidates.append(Path(raw))
    try:
        configured = load_config().get("credentials")
    except ConfigError:
        configured = None
    if isinstance(configured, str) and configured:
        candidates.append(Path(configured))
    candidates.append(Path.home() / ".claude" / ".credentials.json")

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def resolve_credentials_path() -> Path:
    """凭据文件首选路径；无可用候选时回退到用户默认目录。"""
    candidates = resolve_credentials_candidates()
    return candidates[0] if candidates else Path.home() / ".claude" / ".credentials.json"


def resolve_haha_sidecar() -> str:
    """Haha sidecar 路径：WF_HAHA_SIDECAR > 本地配置 haha_sidecar > 空字符串。"""
    raw = os.environ.get("WF_HAHA_SIDECAR")
    if raw:
        return raw
    try:
        configured = load_config().get("haha_sidecar")
    except ConfigError:
        configured = None
    return configured if isinstance(configured, str) and configured else ""


def secret_values() -> list[str]:
    """已知密钥值，用于日志与错误脱敏。"""
    values: list[str] = []
    try:
        secrets = (load_config().get("secrets") or {}).values()
        values.extend(str(v) for v in secrets if isinstance(v, str) and len(v) >= 4)
    except ConfigError:
        pass
    for name in SECRET_ENV_NAMES:
        value = os.environ.get(name)
        if value and len(value) >= 4:
            values.append(value)
    return values


def redact(text: str) -> str:
    if not text:
        return text
    for value in secret_values():
        text = text.replace(value, "***")
    return text


def mask(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return "••••" + value[-4:]


def merge_catalog(catalog: dict[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    """把本地配置覆盖进能力目录：provider 顺序与 CLI 路径。"""
    data = load_config(path)
    capabilities = catalog.get("capabilities") or {}

    providers = data.get("providers") or {}
    for name, chain in providers.items():
        entry = capabilities.get(name)
        if not isinstance(entry, dict):
            raise ConfigError(f"providers 引用了不存在的能力: {name}")
        declared = entry.get("providers") or []
        chain = list(dict.fromkeys(chain))
        unknown = [item for item in chain if item not in declared]
        if unknown:
            raise ConfigError(
                f"providers.{name} 包含未登记 provider: {', '.join(unknown)}"
            )
        entry["primary"] = chain[0]
        entry["alternate"] = chain[1] if len(chain) > 1 else None
        entry["fallback"] = chain[2:]

    cli_paths = data.get("cli_paths") or {}
    for name, mapping in cli_paths.items():
        entry = capabilities.get(name)
        if not isinstance(entry, dict):
            raise ConfigError(f"cli_paths 引用了不存在的能力: {name}")
        exec_map = entry.get("exec") or {}
        for provider, value in mapping.items():
            argv = exec_map.get(provider)
            if not isinstance(argv, list) or not argv:
                raise ConfigError(f"cli_paths.{name} 包含未登记 provider: {provider}")
            if value:
                argv[0] = value

    return catalog


def save_config(data: dict[str, Any], path: str | Path | None = None) -> Path:
    """校验后原子写入；已有文件先备份。"""
    _validate(data)
    target = config_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(target, BACKUP_DIR / f"config-{stamp}.json")
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp, target)
    return target
