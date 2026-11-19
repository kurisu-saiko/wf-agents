"""Tier 1 模块单元测试：决策信封、5选1策略引擎、AST切片闭包与合规 SPDX 追溯。"""

from __future__ import annotations

import pytest

from tools import envelope
from tools.assembly import provenance, slicer, strategy


def test_decision_brief_enforces_four_questions():
    valid = envelope.build_decision_brief(
        requirement_fit="命中 3/3 项需求",
        verifiable_evidence=["Repo: https://github.com/org/lib @ v1.0.0"],
        limitations_and_tradeoffs=["仅支持 Python >=3.10"],
        actionable_options=[{"id": "opt1", "summary": "采用 CODE_SLICE"}],
    )
    ok, issues = envelope.validate_decision_brief(valid)
    assert ok is True
    assert issues == []

    wrapped = envelope.attach_decision_brief({"ok": True, "data": {}}, valid)
    assert wrapped["decision_brief"]["requirement_fit"] == "命中 3/3 项需求"

    with pytest.raises(ValueError):
        envelope.build_decision_brief(
            requirement_fit="",
            verifiable_evidence=[],
            limitations_and_tradeoffs=["tradeoff"],
            actionable_options=[{"summary": "go"}],
        )

    ok_bad, bad_issues = envelope.validate_decision_brief({"requirement_fit": "ok"})
    assert ok_bad is False
    assert len(bad_issues) >= 3


def test_strategy_engine_covers_all_five_scenarios():
    # 1. 同语言小体量宽松许可 + 零新依赖偏好 -> 推荐 CODE_SLICE
    res_slice = strategy.evaluate_strategies(
        candidate={
            "name": "tiny-limiter",
            "language": "Python",
            "license": "MIT",
            "publishedPackage": True,
            "targetFilesCount": 2,
            "estimatedLoc": 280,
        },
        local_profile={"primaryLanguage": "Python", "packageManager": "uv"},
        intent={"preferZeroDependencies": True},
    )
    assert res_slice["recommendedStrategy"] == "CODE_SLICE"
    assert len(res_slice["strategies"]) == 5
    ok, _ = envelope.validate_decision_brief(res_slice["decision_brief"])
    assert ok is True

    # 2. 同语言已发包标准库、无需改源码 -> 推荐 PACKAGE_DEP
    res_pkg = strategy.evaluate_strategies(
        candidate={
            "name": "httpx",
            "language": "Python",
            "license": "BSD-3-Clause",
            "publishedPackage": True,
            "targetFilesCount": 25,
            "estimatedLoc": 8000,
        },
        local_profile={"primaryLanguage": "Python", "packageManager": "uv"},
        intent={"needsSourceModification": False, "preferZeroDependencies": False},
    )
    assert res_pkg["recommendedStrategy"] == "PACKAGE_DEP"

    # 3. 强传染 AGPL 协议 + 闭源商用 -> 封锁直接代码复用，推荐 PATTERN_REF
    res_copyleft = strategy.evaluate_strategies(
        candidate={
            "name": "agpl-core",
            "language": "Python",
            "license": "AGPL-3.0",
            "publishedPackage": True,
            "estimatedLoc": 600,
        },
        local_profile={"primaryLanguage": "Python"},
        intent={"commercialClosedSource": True},
    )
    by_name = {s["strategy"]: s for s in res_copyleft["strategies"]}
    assert by_name["CODE_SLICE"]["feasibility"] == "blocked"
    assert by_name["PACKAGE_DEP"]["feasibility"] == "blocked"
    assert res_copyleft["recommendedStrategy"] == "PATTERN_REF"

    # 4. 跨语言（Python 目标引入到 Go 本地项目）-> 推荐 SIDECAR
    res_cross = strategy.evaluate_strategies(
        candidate={
            "name": "doc-parser",
            "language": "Python",
            "license": "Apache-2.0",
            "publishedPackage": True,
            "estimatedLoc": 5000,
        },
        local_profile={"primaryLanguage": "Go"},
    )
    assert res_cross["recommendedStrategy"] == "SIDECAR"


def test_ast_slicer_computes_minimal_transitive_closure(tmp_path):
    src = tmp_path / "upstream"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (src / "pkg" / "core.py").write_text(
        "import math\nfrom .helpers import clamp\nimport pydantic\n\ndef compute(x: float) -> float:\n    return clamp(math.sqrt(x), 0.0, 10.0)\n",
        encoding="utf-8",
    )
    (src / "pkg" / "helpers.py").write_text(
        "from .constants import MAX_VAL\n\ndef clamp(v: float, lo: float, hi: float) -> float:\n    return min(max(v, lo), hi)\n",
        encoding="utf-8",
    )
    (src / "pkg" / "constants.py").write_text("MAX_VAL = 100\n", encoding="utf-8")
    (src / "pkg" / "unrelated.py").write_text("UNUSED = True\n", encoding="utf-8")

    res = slicer.compute_slice_closure(src, ["pkg/core.py"])
    assert res["closureComplete"] is True
    assert res["closureFiles"] == ["pkg/constants.py", "pkg/core.py", "pkg/helpers.py"]
    assert "pkg/unrelated.py" not in res["closureFiles"]
    assert "math" in res["stdlibImports"]
    assert "pydantic" in res["externalPackages"]
    assert "compute" in res["exportedSymbols"]


def test_slicer_detects_missing_relative_import(tmp_path):
    (tmp_path / "broken.py").write_text("from .does_not_exist import foo\n", encoding="utf-8")
    res = slicer.compute_slice_closure(tmp_path, ["broken.py"])
    assert res["closureComplete"] is False
    assert len(res["missingInternalImports"]) == 1


def test_provenance_spdx_injection_and_notices_idempotent(tmp_path):
    raw = "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n\ndef ok():\n    return 1\n"
    once = provenance.inject_spdx_header(
        raw,
        repo_url="https://github.com/org/repo",
        commit_or_version="v1.2.3",
        spdx_license="MIT",
        original_path="src/mod.py",
    )
    assert once.startswith("#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n")
    assert "# SPDX-License-Identifier: MIT" in once
    assert "# Source-Repository: https://github.com/org/repo" in once

    twice = provenance.inject_spdx_header(
        once,
        repo_url="https://github.com/org/repo",
        commit_or_version="v1.2.3",
        spdx_license="MIT",
        original_path="src/mod.py",
    )
    assert twice == once

    res1 = provenance.update_third_party_notices(
        tmp_path,
        {
            "name": "mod-lib",
            "repo_url": "https://github.com/org/repo",
            "commit_or_version": "v1.2.3",
            "spdx_license": "MIT",
            "strategy": "CODE_SLICE",
            "files": ["adapters/vendor_mod/mod.py"],
        },
    )
    assert res1["created"] is True
    res2 = provenance.update_third_party_notices(
        tmp_path,
        {
            "name": "mod-lib",
            "repo_url": "https://github.com/org/repo",
            "commit_or_version": "v1.2.4",
            "spdx_license": "MIT",
            "strategy": "CODE_SLICE",
            "files": ["adapters/vendor_mod/mod.py"],
        },
    )
    assert res2["created"] is False
    notice_text = (tmp_path / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert notice_text.count("## mod-lib") == 1
    assert "v1.2.4" in notice_text
