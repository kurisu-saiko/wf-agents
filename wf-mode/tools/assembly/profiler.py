"""本地项目深度画像器（Step 3 / Step 4）：

扫描目标本地仓库，识别：
- 主语言与语言分布（reuse repo_utils）
- 包管理器（uv / poetry / pip / pnpm / yarn / npm / cargo / go）
- 目录结构规范（src_layout vs flat_layout），推荐 adapterDir 与 testDir
- 已安装直接依赖与锁文件
- 本地验证探针命令（pytest / py_compile / mypy / ruff / tsc / npm test）
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from tools import repo_utils


def _detect_package_manager(root: Path, files_set: set[str], primary_lang: str) -> str:
    if (root / "uv.lock").is_file() or "uv.lock" in files_set:
        return "uv"
    if (root / "poetry.lock").is_file() or "poetry.lock" in files_set:
        return "poetry"
    if (root / "pnpm-lock.yaml").is_file() or "pnpm-lock.yaml" in files_set:
        return "pnpm"
    if (root / "yarn.lock").is_file() or "yarn.lock" in files_set:
        return "yarn"
    if (root / "package-lock.json").is_file() or "package-lock.json" in files_set:
        return "npm"
    if (root / "Cargo.toml").is_file() or "Cargo.toml" in files_set:
        return "cargo"
    if (root / "go.mod").is_file() or "go.mod" in files_set:
        return "go"
    if primary_lang == "Python":
        return "pip"
    if primary_lang in {"TypeScript", "JavaScript"}:
        return "npm"
    return "unknown"


def _detect_layout(root: Path, files: list[str], primary_lang: str) -> dict[str, Any]:
    has_src_dir = (root / "src").is_dir()
    has_app_dir = (root / "app").is_dir()
    has_tests_dir = (root / "tests").is_dir() or (root / "test").is_dir()

    pkg_dirs = [
        p.name
        for p in sorted(root.iterdir())
        if p.is_dir()
        and p.name not in repo_utils.IGNORE_DIRS
        and not p.name.startswith(".")
        and p.name not in {"tests", "test", "docs", "scripts", "adapters"}
    ]

    if has_src_dir:
        layout = "src_layout"
        # 查找 src/<pkg> 如果存在单一主包
        src_subs = [p.name for p in sorted((root / "src").iterdir()) if p.is_dir() and not p.name.startswith(".")]
        if len(src_subs) == 1 and primary_lang == "Python" and ((root / "src" / src_subs[0] / "__init__.py").is_file()):
            adapter_dir = f"src/{src_subs[0]}/adapters"
        else:
            adapter_dir = "src/adapters"
    elif has_app_dir:
        layout = "app_layout"
        adapter_dir = "app/adapters"
    elif len(pkg_dirs) == 1 and primary_lang == "Python" and (root / pkg_dirs[0] / "__init__.py").is_file():
        layout = "package_layout"
        adapter_dir = f"{pkg_dirs[0]}/adapters"
    else:
        layout = "flat_layout"
        adapter_dir = "adapters"

    test_dir = "test" if (root / "test").is_dir() and not (root / "tests").is_dir() else "tests"

    # 识别常用源根路径，便于计算 import 路径
    is_python = primary_lang == "Python"
    return {
        "layout": layout,
        "adapterDir": adapter_dir,
        "testDir": test_dir,
        "hasSrcDir": has_src_dir,
        "hasTestsDir": has_tests_dir,
        "moduleStyle": "python_package" if is_python else "es_module",
    }


def _detect_verification_probes(
    root: Path,
    manifest_texts: dict[str, str],
    primary_lang: str,
) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    pyproject = manifest_texts.get("pyproject.toml", "")
    pkg_json_raw = manifest_texts.get("package.json", "")

    if primary_lang == "Python":
        probes.append({"name": "syntax_compile", "cmd": [sys.executable, "-m", "py_compile"]})
        if "pytest" in pyproject.lower() or (root / "tests").is_dir() or (root / "pytest.ini").is_file():
            probes.append({"name": "pytest", "cmd": [sys.executable, "-m", "pytest", "-q"]})
        if "ruff" in pyproject.lower():
            probes.append({"name": "ruff", "cmd": ["ruff", "check", "."]})
        if "mypy" in pyproject.lower():
            probes.append({"name": "mypy", "cmd": ["mypy", "."]})

    elif primary_lang in {"TypeScript", "JavaScript"}:
        try:
            pkg = json.loads(pkg_json_raw) if pkg_json_raw else {}
        except ValueError:
            pkg = {}
        scripts = pkg.get("scripts") if isinstance(pkg, dict) else {}
        if isinstance(scripts, dict):
            if "test" in scripts:
                probes.append({"name": "npm_test", "cmd": ["npm", "test"]})
            if "typecheck" in scripts:
                probes.append({"name": "npm_typecheck", "cmd": ["npm", "run", "typecheck"]})
            if "lint" in scripts:
                probes.append({"name": "npm_lint", "cmd": ["npm", "run", "lint"]})
        if (root / "tsconfig.json").is_file():
            probes.append({"name": "tsc", "cmd": ["npx", "tsc", "--noEmit"]})

    elif primary_lang == "Go" and (root / "go.mod").is_file():
        probes.append({"name": "go_test", "cmd": ["go", "test", "./..."]})

    elif primary_lang == "Rust" and (root / "Cargo.toml").is_file():
        probes.append({"name": "cargo_check", "cmd": ["cargo", "check"]})

    return probes


def profile_local_project(path: str | Path = ".") -> dict[str, Any]:
    """扫描本地工作区，生成供 Step 3 策略评估与 Step 4 对接设计使用的结构化画像。"""
    root = repo_utils.resolve_local_path(path)
    if root.is_file():
        root = root.parent

    files = repo_utils.iter_project_files(root, max_files=2500)
    files_set = set(files)

    lang_counts: Counter[str] = Counter()
    manifest_texts: dict[str, str] = {}
    manifests: list[str] = []
    lockfiles: list[str] = []

    for rel in files:
        name = Path(rel).name
        lang = repo_utils.detect_language(rel)
        if lang and lang not in {"Markdown", "JSON", "YAML", "TOML", "HTML", "CSS"}:
            lang_counts[lang] += 1
        if name in repo_utils.MANIFEST_FILES or (name.startswith("requirements") and name.endswith(".txt")):
            manifests.append(rel)
            try:
                manifest_texts[rel] = (root / rel).read_text(encoding="utf-8", errors="replace")[:200000]
            except OSError:
                pass
        if name in repo_utils.LOCKFILE_NAMES:
            lockfiles.append(rel)
            if name not in manifest_texts:
                try:
                    manifest_texts[rel] = (root / rel).read_text(encoding="utf-8", errors="replace")[:500000]
                except OSError:
                    pass

    if not lang_counts:
        if any(m.endswith(("pyproject.toml", "requirements.txt")) for m in manifests):
            lang_counts["Python"] = 1
        elif any(m.endswith("package.json") for m in manifests):
            lang_counts["TypeScript" if (root / "tsconfig.json").is_file() else "JavaScript"] = 1

    primary_language = lang_counts.most_common(1)[0][0] if lang_counts else "Unknown"
    package_manager = _detect_package_manager(root, files_set, primary_language)
    layout_info = _detect_layout(root, files, primary_language)
    deps = repo_utils.parse_dependencies_from_texts(manifest_texts)
    probes = _detect_verification_probes(root, manifest_texts, primary_language)

    return {
        "projectRoot": str(root),
        "primaryLanguage": primary_language,
        "languages": dict(lang_counts),
        "packageManager": package_manager,
        "manifests": sorted(manifests),
        "lockfiles": sorted(lockfiles),
        "existingDependenciesCount": len(deps),
        "existingDependencies": deps[:50],
        **layout_info,
        "verificationProbes": probes,
        "totalFilesScanned": len(files),
        "isGitRepo": (root / ".git").exists(),
    }
