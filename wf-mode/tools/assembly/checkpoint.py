"""工作区安全检查点与一键回滚管理器（Step 5 & Step 6 兜底保障）。

在任何组装写盘前，为受影响路径（以及 Git HEAD 状态）拍摄完整快照保存在
`<project_path>/.wf/checkpoints/<checkpoint_id>/`。
支持 1 秒精确还原被修改文件的原字节内容，并删除组装阶段新创建的文件。
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tools.errors import ToolError
from tools.util import utc_now

_DEFAULT_WATCH_FILES = (
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "package-lock.json",
    "go.mod",
    "Cargo.toml",
)


def _checkpoints_root(project_root: Path) -> Path:
    return project_root / ".wf" / "checkpoints"


def _run_git(project_root: Path, args: list[str]) -> str:
    if not (project_root / ".git").exists():
        return ""
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _safe_rel(project_root: Path, raw_path: str) -> str:
    cleaned = raw_path.replace("\\", "/").lstrip("./")
    resolved = (project_root / cleaned).resolve()
    try:
        rel = resolved.relative_to(project_root.resolve()).as_posix()
    except ValueError as exc:
        raise ToolError("INVALID_INPUT", f"检查点路径越界: {raw_path}") from exc
    return rel


def create_checkpoint(
    project_path: str | Path,
    label: str = "assembly",
    planned_files: list[str] | None = None,
) -> dict[str, Any]:
    """创建组装前安全检查点快照。"""
    project_root = Path(project_path).expanduser().resolve()
    if not project_root.is_dir():
        raise ToolError("INVALID_INPUT", f"项目目录不存在: {project_path}")

    stamp = utc_now().replace(":", "").replace("-", "").replace("Z", "")
    ck_id = f"ck-{stamp}-{secrets.token_hex(3)}"
    ck_dir = _checkpoints_root(project_root) / ck_id
    blobs_dir = ck_dir / "blobs"
    blobs_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[str] = []
    seen: set[str] = set()
    for p in [*list(_DEFAULT_WATCH_FILES), *list(planned_files or [])]:
        rel = _safe_rel(project_root, p)
        if rel not in seen:
            seen.add(rel)
            candidates.append(rel)

    files_meta: list[dict[str, Any]] = []
    for idx, rel in enumerate(candidates):
        target = project_root / rel
        if target.is_file():
            raw = target.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            blob_name = f"blob_{idx}_{sha[:12]}"
            (blobs_dir / blob_name).write_bytes(raw)
            files_meta.append(
                {
                    "path": rel,
                    "existed": True,
                    "blob": blob_name,
                    "sha256": sha,
                }
            )
        else:
            files_meta.append(
                {
                    "path": rel,
                    "existed": False,
                    "blob": "",
                    "sha256": "",
                }
            )

    manifest = {
        "checkpointId": ck_id,
        "label": label,
        "createdAt": utc_now(),
        "status": "active",
        "projectRoot": str(project_root),
        "gitHead": _run_git(project_root, ["rev-parse", "HEAD"]),
        "gitBranch": _run_git(project_root, ["rev-parse", "--abbrev-ref", "HEAD"]),
        "gitStatusBefore": _run_git(project_root, ["status", "--porcelain"]),
        "files": files_meta,
    }
    snap_path = ck_dir / "snapshot.json"
    snap_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def list_checkpoints(project_path: str | Path) -> list[dict[str, Any]]:
    project_root = Path(project_path).expanduser().resolve()
    root = _checkpoints_root(project_root)
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for sub in sorted(root.iterdir(), reverse=True):
        snap = sub / "snapshot.json"
        if snap.is_file():
            try:
                data = json.loads(snap.read_text(encoding="utf-8"))
                items.append(data)
            except (OSError, ValueError):
                continue
    return items


def _prune_empty_parents(start_dir: Path, stop_root: Path) -> None:
    cur = start_dir
    stop = stop_root.resolve()
    while cur.resolve() != stop and cur.is_dir():
        try:
            if any(cur.iterdir()):
                break
            cur.rmdir()
        except OSError:
            break
        cur = cur.parent


def rollback_checkpoint(
    project_path: str | Path,
    checkpoint_id: str | None = None,
) -> dict[str, Any]:
    """一键精确回滚指定检查点（或最近一个 active 检查点）。"""
    project_root = Path(project_path).expanduser().resolve()
    ck_root = _checkpoints_root(project_root)

    if checkpoint_id:
        snap_path = ck_root / checkpoint_id / "snapshot.json"
        if not snap_path.is_file():
            raise ToolError("INVALID_INPUT", f"找不到检查点: {checkpoint_id}")
        manifest = json.loads(snap_path.read_text(encoding="utf-8"))
    else:
        all_ck = list_checkpoints(project_root)
        active = [c for c in all_ck if c.get("status") == "active"] or all_ck
        if not active:
            raise ToolError("INVALID_INPUT", "当前项目没有可回滚的安全检查点")
        manifest = active[0]
        checkpoint_id = manifest["checkpointId"]
        snap_path = ck_root / checkpoint_id / "snapshot.json"

    ck_dir = ck_root / checkpoint_id
    blobs_dir = ck_dir / "blobs"
    restored: list[str] = []
    deleted: list[str] = []

    for entry in manifest.get("files") or []:
        rel = str(entry.get("path") or "")
        if not rel:
            continue
        target = project_root / _safe_rel(project_root, rel)
        if entry.get("existed"):
            blob_file = blobs_dir / str(entry.get("blob") or "")
            if blob_file.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob_file.read_bytes())
                restored.append(rel)
        else:
            if target.is_file():
                target.unlink()
                deleted.append(rel)
                _prune_empty_parents(target.parent, project_root)

    # 清理 Python __pycache__ 避免残余空目录影响 git status
    for cache_dir in project_root.rglob("__pycache__"):
        if ".venv" in cache_dir.parts or ".git" in cache_dir.parts or ".wf" in cache_dir.parts:
            continue
        try:
            shutil.rmtree(cache_dir)
            _prune_empty_parents(cache_dir.parent, project_root)
        except OSError:
            pass

    manifest["status"] = "rolled_back"
    manifest["rolledBackAt"] = utc_now()
    snap_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "checkpointId": checkpoint_id,
        "status": "rolled_back",
        "restoredFiles": restored,
        "deletedCreatedFiles": deleted,
        "gitStatusAfter": _run_git(project_root, ["status", "--porcelain"]),
    }
