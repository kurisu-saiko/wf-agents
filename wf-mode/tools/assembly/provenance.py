"""开源合规追溯与 SPDX 版权声明工具（Step 5）：

1. 为抽取或内嵌的第三方源码自动幂等注入 SPDX 与来源追溯文件头
2. 自动创建或更新项目根目录下的 THIRD_PARTY_NOTICES.md
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tools.util import utc_now

_SLASH_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".c", ".cpp"}


def _comment_prefix(original_path: str) -> str:
    ext = Path(original_path).suffix.lower()
    return "//" if ext in _SLASH_EXTS else "#"


def inject_spdx_header(
    content: str,
    *,
    repo_url: str,
    commit_or_version: str,
    spdx_license: str,
    original_path: str,
) -> str:
    """在源码顶部幂等注入 SPDX 许可证与上游溯源头注释，保留 shebang / encoding 行。"""
    prefix = _comment_prefix(original_path)
    if re.search(r"SPDX-License-Identifier\s*:", content):
        return content

    header_lines = [
        f"{prefix} SPDX-License-Identifier: {spdx_license or 'UNKNOWN'}",
        f"{prefix} Source-Repository: {repo_url}",
        f"{prefix} Source-Version: {commit_or_version or 'HEAD'}",
        f"{prefix} Original-Path: {original_path}",
    ]
    lines = content.splitlines(keepends=True)
    preserved: list[str] = []
    idx = 0
    if idx < len(lines) and lines[idx].startswith("#!"):
        preserved.append(lines[idx])
        idx += 1
    if idx < len(lines) and re.match(r"^#.*coding[:=]", lines[idx]):
        preserved.append(lines[idx])
        idx += 1

    nl = "\n"
    header_block = nl.join(header_lines) + nl + nl
    rest = "".join(lines[idx:])
    return "".join(preserved) + header_block + rest


def format_notice_section(
    *,
    name: str,
    repo_url: str,
    commit_or_version: str,
    spdx_license: str,
    strategy: str,
    files: list[str],
    notes: str = "",
) -> str:
    """渲染单条第三方开源组件追溯章节（Markdown）。"""
    marker_start = f"<!-- wf-notice:{name} -->"
    marker_end = f"<!-- /wf-notice:{name} -->"
    lines = [
        marker_start,
        f"## {name}",
        "",
        f"- **Repository / Package**: {repo_url}",
        f"- **License (SPDX)**: `{spdx_license or 'UNKNOWN'}`",
        f"- **Version / Commit**: `{commit_or_version or 'HEAD'}`",
        f"- **Reuse Strategy**: `{strategy}`",
        f"- **Recorded At**: `{utc_now()}`",
    ]
    if files:
        lines.append("- **Integrated / Referenced Files**:")
        for f in files:
            lines.append(f"  - `{f}`")
    if notes.strip():
        lines.append(f"- **Compliance Notes**: {notes.strip()}")
    lines.append(marker_end)
    return "\n".join(lines) + "\n"


def render_updated_notices(existing_text: str, notice_data: dict[str, Any]) -> str:
    """纯函数计算更新后的 THIRD_PARTY_NOTICES.md 文本，便于 Diff 预览与测试。"""
    name = str(notice_data.get("name") or "third-party-component").strip()
    section = format_notice_section(
        name=name,
        repo_url=str(notice_data.get("repo_url") or notice_data.get("repoUrl") or ""),
        commit_or_version=str(notice_data.get("commit_or_version") or notice_data.get("version") or "HEAD"),
        spdx_license=str(notice_data.get("spdx_license") or notice_data.get("license") or "UNKNOWN"),
        strategy=str(notice_data.get("strategy") or "CODE_SLICE"),
        files=[str(f) for f in (notice_data.get("files") or [])],
        notes=str(notice_data.get("notes") or ""),
    )

    header = (
        "# Third-Party Software Notices\n\n"
        "This file records open-source components reused or integrated via `wf-agents`,\n"
        "including exact upstream provenance, versions/commits, and SPDX license identifiers.\n\n"
    )
    text = existing_text if existing_text.strip() else header
    pattern = re.compile(
        re.escape(f"<!-- wf-notice:{name} -->") + r".*?" + re.escape(f"<!-- /wf-notice:{name} -->") + r"\n?",
        re.S,
    )
    if pattern.search(text):
        return pattern.sub(section, text, count=1).rstrip() + "\n"
    return text.rstrip() + "\n\n" + section


def update_third_party_notices(project_path: str | Path, notice_data: dict[str, Any]) -> dict[str, Any]:
    """创建或幂等更新目标项目根目录的 THIRD_PARTY_NOTICES.md。"""
    root = Path(project_path).expanduser().resolve()
    notice_file = root / "THIRD_PARTY_NOTICES.md"
    existing = notice_file.read_text(encoding="utf-8") if notice_file.is_file() else ""
    updated = render_updated_notices(existing, notice_data)
    notice_file.write_text(updated, encoding="utf-8")
    return {
        "path": str(notice_file),
        "created": not bool(existing),
        "component": str(notice_data.get("name") or "third-party-component"),
        "content": updated,
    }
