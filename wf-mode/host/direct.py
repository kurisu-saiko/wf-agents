"""直连快速通道：查看/结构类任务不启 agent，直接读本地仓库或调 wf-tool。

只做只读操作：git 查询、目录列举、project_search lookup。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF_TOOL = ROOT / "tools" / "wf-tool.py"

DIRECT_HINTS = (
    "查看", "看看", "看一下", "列一下", "列出", "目录", "文件树", "文件列表",
    "结构", "架构", "内容", "有哪些文件", "当前仓库", "这个仓库", "仓库内容",
    "本地仓库", "读一下", "打开", "长什么样",
)
LOCAL_HINTS = (
    "仓库", "repo", "github", "目录", "文件", "结构", "架构", "代码库",
    "本地", "当前项目", "readme",
)
EXCLUDE_HINTS = (
    "采用", "选型", "推荐", "替代", "值不值得", "评估", "对比", "方案",
    "能不能用", "怎么用", "集成", "部署", "迁移", "自建", "技术栈",
)

GITHUB_RE = re.compile(
    r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)",
    re.I,
)
REPO_RE = re.compile(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
PATH_RE = re.compile(r"([A-Za-z]:[\\/][^\s\"'，。；]+)")


def should_direct(task: str) -> bool:
    text = str(task).lower()
    if any(word in text for word in EXCLUDE_HINTS):
        return False
    return any(word in text for word in DIRECT_HINTS) and any(
        word in text for word in LOCAL_HINTS
    )


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or proc.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _git(path: Path, *args: str) -> str:
    if not shutil.which("git"):
        return ""
    code, out = _run(["git", "-C", str(path), *args])
    return out if code == 0 else ""


def _git_root(start: Path) -> Path | None:
    current = start.resolve()
    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _nearby_repos(start: Path) -> list[Path]:
    for base in (start, start.parent, start.parent.parent):
        found: dict[str, Path] = {}
        try:
            children = list(base.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and (child / ".git").exists():
                found[str(child.resolve())] = child.resolve()
        if found:
            return sorted(found.values(), key=lambda p: p.name.lower())
    return []


def _remote(path: Path) -> str:
    remote = _git(path, "remote", "get-url", "origin")
    if remote:
        return remote
    config = path / ".git" / "config"
    try:
        match = re.search(r"url\s*=\s*(\S+)", config.read_text(encoding="utf-8", errors="replace"))
        return match.group(1) if match else ""
    except OSError:
        return ""


def _branch(path: Path) -> str:
    branch = _git(path, "symbolic-ref", "--short", "HEAD")
    if branch:
        return branch
    try:
        head = (path / ".git" / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    return head.split("/")[-1] if head.startswith("ref:") else head[:7]


def _commit(path: Path) -> str:
    commit = _git(path, "log", "-1", "--format=%h %s")
    if commit:
        return commit
    return ""


def _top_entries(path: Path, limit: int = 25) -> str:
    try:
        items = sorted(path.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return "-"
    names = []
    for item in items:
        if item.name == ".git":
            continue
        names.append(item.name + "/" if item.is_dir() else item.name)
    if len(names) > limit:
        names = names[:limit] + [f"...（共 {len(names)} 项）"]
    return "  ".join(names) or "-"


def _is_local_relative(token: str) -> bool:
    start = Path.cwd()
    for base in (start, *list(start.parents)[:3]):
        try:
            if (base / token).exists():
                return True
        except OSError:
            continue
    return False


def _parse_target(task: str) -> str:
    match = GITHUB_RE.search(task)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    cleaned = PATH_RE.sub(" ", task)
    for owner, name in REPO_RE.findall(cleaned):
        token = f"{owner}/{name}"
        if owner.lower() in {"http", "https", "d", "c", "e", "f"}:
            continue
        if len(owner) < 2 or _is_local_relative(token):
            continue
        return token
    return ""


def _parse_path(task: str) -> Path | None:
    match = PATH_RE.search(task)
    if not match:
        return None
    path = Path(match.group(1)).expanduser()
    return path if path.exists() else None


def _lookup(target: str) -> list[str]:
    code, out = _run(
        [sys.executable, str(WF_TOOL), "call", "project_search", "lookup", "--repo", target],
        timeout=25,
    )
    try:
        envelope = json.loads(out)
    except (TypeError, ValueError):
        return [f"远程：查询失败（{out[:120]}）"]
    if not envelope.get("ok"):
        err = (envelope.get("error") or {}).get("message") or "未知错误"
        return [f"远程：查询失败（{err}）"]
    item = (envelope.get("data") or {}).get("candidate") or {}
    license_name = item.get("license") or "无"
    archived = "是" if item.get("archived") else "否"
    lines = [
        f"仓库：{item.get('fullName') or target}",
        f"链接：{item.get('url') or ''}",
        f"更新：{item.get('updatedAt') or '-'}  星标：{item.get('stars') or 0}  许可：{license_name}  归档：{archived}",
    ]
    if item.get("description"):
        lines.append(f"说明：{item['description']}")
    return lines


def _local_summary(path: Path) -> list[str]:
    lines = [f"仓库：{path.as_posix()}"]
    remote = _remote(path)
    if remote:
        lines.append(f"远程：{remote}")
    branch = _branch(path)
    commit = _commit(path)
    head = "  ".join(part for part in (f"分支：{branch}" if branch else "", f"提交：{commit}" if commit else "") if part)
    if head:
        lines.append(head)
    lines.append(f"顶层：{_top_entries(path)}")
    return lines


def run(task: str) -> str | None:
    target = _parse_target(task)
    explicit = _parse_path(task)
    start = explicit or Path.cwd()
    local = _git_root(start)

    if local and (not target or _matches(local, target)):
        return "\n".join(_local_summary(local))

    if explicit and local is None:
        if explicit.is_dir():
            return "\n".join([f"目录：{explicit.as_posix()}", f"顶层：{_top_entries(explicit)}"])
        if explicit.is_file():
            return f"文件：{explicit.as_posix()}（{explicit.stat().st_size} 字节）"

    lines: list[str] = []
    if target:
        lines.extend(_lookup(target))

    if local is None:
        nearby = _nearby_repos(start)
        if len(nearby) == 1:
            lines.append("当前目录不是 git 仓库，使用附近唯一的仓库：")
            lines.extend(_local_summary(nearby[0]))
        elif nearby:
            lines.append(f"当前目录不是 git 仓库；附近找到 {len(nearby)} 个仓库：")
            for repo in nearby[:8]:
                lines.append(f"- {repo.name}  {repo.as_posix()}")
            if len(nearby) > 8:
                lines.append(f"  ...（共 {len(nearby)} 个）")
        elif not lines:
            return None

    return "\n".join(lines)


def _matches(path: Path, target: str) -> bool:
    remote = _remote(path).lower()
    return target.lower() in remote or path.name.lower() == target.split("/")[-1].lower()
