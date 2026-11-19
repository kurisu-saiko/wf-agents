"""5选1开源复用策略评估引擎（Step 3 & Gate 3）。

结合候选项目画像（许可证、语言栈、发包情况、漏洞与体量）与本地项目画像、
开发者复用意图，量化评估五种策略：
1. PACKAGE_DEP  (包依赖导入)
2. CODE_SLICE   (代码切片最小闭包抽取)
3. VENDORING    (整库源码内嵌/子模块)
4. SIDECAR      (独立伴生进程/容器服务)
5. PATTERN_REF  (净室模式/架构参考重写)
"""

from __future__ import annotations

from typing import Any

from tools import envelope as wf_envelope
from tools import repo_utils

STRATEGIES = (
    "PACKAGE_DEP",
    "CODE_SLICE",
    "VENDORING",
    "SIDECAR",
    "PATTERN_REF",
)

STRATEGY_TITLES: dict[str, str] = {
    "PACKAGE_DEP": "包依赖导入 (Package Dependency)",
    "CODE_SLICE": "代码切片抽取 (Code Slicing)",
    "VENDORING": "源码内嵌 (Source Vendoring)",
    "SIDECAR": "伴生服务隔离 (Sidecar / CLI Service)",
    "PATTERN_REF": "模式参考重写 (Clean-Room Pattern Reference)",
}

_LANG_TO_ECOSYSTEM: dict[str, str] = {
    "python": "python",
    "py": "python",
    "typescript": "js",
    "ts": "js",
    "javascript": "js",
    "js": "js",
    "go": "go",
    "golang": "go",
    "rust": "rust",
    "rs": "rust",
}


def _norm_eco(lang: str | None) -> str:
    cleaned = (lang or "").strip().lower()
    return _LANG_TO_ECOSYSTEM.get(cleaned, cleaned or "unknown")


def evaluate_strategies(
    *,
    candidate: dict[str, Any],
    local_profile: dict[str, Any] | None = None,
    intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """针对候选项目与本地工程画像，量化评估 5 种复用策略并生成 Gate 3 决策简报。"""
    local_profile = dict(local_profile or {})
    intent = dict(intent or {})

    cand_name = str(candidate.get("name") or candidate.get("repo") or "candidate").strip()
    cand_lang = str(candidate.get("language") or "").strip()
    local_lang = str(local_profile.get("primaryLanguage") or cand_lang).strip()
    cand_eco = _norm_eco(cand_lang)
    local_eco = _norm_eco(local_lang)
    same_eco = cand_eco == local_eco or cand_eco == "unknown" or local_eco == "unknown"

    spdx = str(candidate.get("license") or "UNKNOWN").strip()
    lic_cat = str(candidate.get("licenseCategory") or repo_utils.license_category(spdx)).strip().lower()
    closed_source = bool(intent.get("commercialClosedSource", True))

    published = bool(candidate.get("publishedPackage") or candidate.get("packageName"))
    customize_source = bool(intent.get("needsSourceModification", False))
    zero_new_deps = bool(intent.get("preferZeroDependencies", False))
    target_files_count = int(candidate.get("targetFilesCount") or intent.get("targetFilesCount") or 0)
    estimated_loc = int(candidate.get("estimatedLoc") or candidate.get("loc") or 0)
    cve_count = int(candidate.get("cveCount") or 0)
    repo_url = str(candidate.get("url") or candidate.get("repoUrl") or "").strip()

    strong_copyleft_restricted = lic_cat == "strong-copyleft" and closed_source
    small_slice_candidate = (1 <= target_files_count <= 5) or (0 < estimated_loc <= 1500)

    evaluations: list[dict[str, Any]] = []

    def add(
        key: str,
        score: int,
        feasibility: str,
        pros: list[str],
        cons: list[str],
        cost: dict[str, str],
    ) -> None:
        clamped = max(0, min(100, score))
        evaluations.append(
            {
                "strategy": key,
                "title": STRATEGY_TITLES[key],
                "score": clamped,
                "feasibility": feasibility,
                "pros": pros,
                "cons": cons,
                "cost_matrix": cost,
            }
        )

    # 1. PACKAGE_DEP
    pkg_score = 72
    pkg_pros: list[str] = []
    pkg_cons: list[str] = []
    pkg_feasibility = "viable"
    if not same_eco:
        pkg_score = 5
        pkg_feasibility = "blocked"
        pkg_cons.append(f"语言生态不匹配（候选为 {cand_lang or cand_eco}，本地为 {local_lang or local_eco}）")
    elif strong_copyleft_restricted:
        pkg_score = 10
        pkg_feasibility = "blocked"
        pkg_cons.append(f"许可证 `{spdx}` 属于强传染性协议，在闭源商用约束下直接依赖存在法务传染风险")
    elif not published:
        pkg_score = 22
        pkg_feasibility = "discouraged"
        pkg_cons.append("未检索到已发布的标准包元数据（PyPI/npm/crates），仅可通过 git URL 安装")
    else:
        pkg_pros.append(f"已发布标准软件包，可通过 `{local_profile.get('packageManager') or '包管理器'}` 标准化升级")
        if customize_source:
            pkg_score -= 35
            pkg_feasibility = "discouraged"
            pkg_cons.append("需求要求深度修改上游内部实现，包依赖难以直接打补丁")
        else:
            pkg_score += 18
            pkg_pros.append("无需定制内部源码，直接以薄 Adapter 封装即可")
        if zero_new_deps:
            pkg_score -= 22
            pkg_cons.append("当前偏好“零额外传递依赖”，直接安装包会引入第三方传递依赖树")
        if small_slice_candidate:
            pkg_score -= 10
            pkg_cons.append("仅需候选库极少量核心代码，整包安装略显冗余")
        if cve_count > 0:
            pkg_score -= min(30, cve_count * 12)
            pkg_cons.append(f"检测到 {cve_count} 项已知漏洞，需评估影响范围与修复版本")
    add(
        "PACKAGE_DEP",
        pkg_score,
        pkg_feasibility,
        pkg_pros or ["标准依赖升级与安全审计路径清晰"],
        pkg_cons or ["受限于上游发布周期"],
        {"integration_effort": "低", "maintenance_burden": "低（上游维护）", "license_risk": lic_cat},
    )

    # 2. CODE_SLICE
    slice_score = 60
    slice_pros: list[str] = []
    slice_cons: list[str] = []
    slice_feasibility = "viable"
    if not same_eco:
        slice_score = 5
        slice_feasibility = "blocked"
        slice_cons.append(f"跨语言（{cand_lang} -> {local_lang}）无法直接复用代码切片")
    elif strong_copyleft_restricted:
        slice_score = 0
        slice_feasibility = "blocked"
        slice_cons.append(f"强传染协议 `{spdx}` 严禁将源码片段直接复制进闭源商用仓库")
    else:
        if lic_cat == "weak-copyleft":
            slice_score -= 20
            slice_cons.append(f"弱传染协议 `{spdx}` 对改动后切片有同文件/模块公开要求，需谨慎隔离")
        else:
            slice_pros.append(f"许可证 `{spdx}` 允许在保留版权声明与 SPDX 头的前提下抽取集成")
        if small_slice_candidate:
            slice_score += 24
            slice_pros.append(
                f"目标范围收敛（文件数≈{target_files_count or '少量'}，LOC≈{estimated_loc or '可控'}），可计算最小 AST 闭包"
            )
        if not published:
            slice_score += 15
            slice_pros.append("不依赖公共包源发布状态")
        if zero_new_deps:
            slice_score += 18
            slice_pros.append("彻底避免引入外部重型传递依赖")
        if customize_source:
            slice_score += 12
            slice_pros.append("切片入库后可直接结合本地业务契约微调")
        if estimated_loc > 3000:
            slice_score -= 25
            slice_feasibility = "discouraged"
            slice_cons.append(f"预估代码量较大（{estimated_loc} LOC），切片长期同步成本高")
    add(
        "CODE_SLICE",
        slice_score,
        slice_feasibility,
        slice_pros or ["精确控制入库代码与零传递依赖"],
        slice_cons or ["上游后续 bugfix 需手动或通过 wf 重新比对同步"],
        {"integration_effort": "中", "maintenance_burden": "中（需同步上游安全补丁）", "license_risk": lic_cat},
    )

    # 3. VENDORING
    vendor_score = 42
    vendor_pros: list[str] = []
    vendor_cons: list[str] = []
    vendor_feasibility = "viable"
    if not same_eco:
        vendor_score = 5
        vendor_feasibility = "blocked"
        vendor_cons.append("跨语言项目无法以同进程源码直接 vendor")
    elif strong_copyleft_restricted:
        vendor_score = 5
        vendor_feasibility = "blocked"
        vendor_cons.append(f"强传染协议 `{spdx}` 禁止整库内嵌进闭源仓库")
    else:
        if customize_source and not small_slice_candidate:
            vendor_score += 38
            vendor_pros.append("既要保留完整库能力，又允许在 vendor/ 下做深度定制修改")
        else:
            vendor_cons.append("整库内嵌会显著增加仓库体积与静态扫描噪音")
        if not published and not small_slice_candidate:
            vendor_score += 20
            vendor_pros.append("适合未发包但体量完整的库")
    add(
        "VENDORING",
        vendor_score,
        vendor_feasibility,
        vendor_pros or ["锁定特定版本源码、彻底消除外网构建依赖"],
        vendor_cons or ["目录体量大、需自维护构建路径挂载"],
        {"integration_effort": "中~高", "maintenance_burden": "高", "license_risk": lic_cat},
    )

    # 4. SIDECAR
    sidecar_score = 35
    sidecar_pros: list[str] = []
    sidecar_cons: list[str] = []
    sidecar_feasibility = "viable"
    if not same_eco:
        sidecar_score = 84
        sidecar_pros.append(f"完美解决跨语言鸿沟（{cand_lang or cand_eco} 与本地 {local_lang or local_eco} 进程解耦）")
    elif strong_copyleft_restricted:
        sidecar_score = 72
        sidecar_pros.append(f"通过独立 CLI/HTTP 进程边界隔离强传染协议 `{spdx}`（注意网络服务场景下 AGPL 仍受限）")
        if "AGPL" in spdx.upper():
            sidecar_score -= 25
            sidecar_feasibility = "discouraged"
            sidecar_cons.append("AGPL 协议在网络服务场景下即便作为独立伴生服务仍触发源码公开条款")
    else:
        sidecar_cons.append("同语言且许可证宽松时，引入独立进程/容器的运维复杂度过高")
        sidecar_feasibility = "discouraged"
    sidecar_cons.append("引入进程间通信延迟（CLI/HTTP）及部署生命周期管理成本")
    add(
        "SIDECAR",
        sidecar_score,
        sidecar_feasibility,
        sidecar_pros or ["进程与依赖完全隔离，跨语言零冲突"],
        sidecar_cons,
        {"integration_effort": "高", "maintenance_burden": "中~高（进程编排与监控）", "license_risk": "进程边界隔离"},
    )

    # 5. PATTERN_REF
    ref_score = 32
    ref_pros: list[str] = ["完全自主可控、零第三方版权传染与外部漏洞传递风险"]
    ref_cons: list[str] = ["开发实现与单元测试编写工作量最大"]
    ref_feasibility = "viable"
    if strong_copyleft_restricted:
        ref_score = 88
        ref_pros.insert(0, f"唯一彻底规避 `{spdx}` 传染性限制的合规路径：仅参考架构与接口契约进行净室重写")
    elif not same_eco and estimated_loc <= 1200:
        ref_score = 70
        ref_pros.insert(0, "体量较小且跨语言时，净室移植比拉起 Sidecar 服务更轻量")
    add(
        "PATTERN_REF",
        ref_score,
        ref_feasibility,
        ref_pros,
        ref_cons,
        {"integration_effort": "高", "maintenance_burden": "自维护", "license_risk": "none (clean-room)"},
    )

    # 排序并标定唯一推荐项
    evaluations.sort(key=lambda item: (-item["score"], STRATEGIES.index(item["strategy"])))
    for idx, item in enumerate(evaluations):
        if idx == 0 and item["feasibility"] != "blocked":
            item["feasibility"] = "recommended"

    top = evaluations[0]
    recommended = top["strategy"]

    evidences: list[str] = [
        f"Candidate: {cand_name}" + (f" ({repo_url})" if repo_url else ""),
        f"Ecosystems: candidate={cand_lang or cand_eco}, local={local_lang or local_eco}, same_ecosystem={same_eco}",
        f"License: {spdx} (category={lic_cat}, commercialClosedSource={closed_source})",
        f"Package Published: {published}, Target Files: {target_files_count}, Estimated LOC: {estimated_loc}, CVEs: {cve_count}",
    ]
    tradeoffs: list[str] = []
    for item in evaluations[:3]:
        tradeoffs.append(f"[{item['strategy']} / {item['score']}分] 优点: {item['pros'][0]}；代价: {item['cons'][0]}")

    options = [
        {
            "id": f"strategy_{item['strategy'].lower()}",
            "strategy": item["strategy"],
            "score": item["score"],
            "feasibility": item["feasibility"],
            "recommended": item["strategy"] == recommended,
            "summary": f"{item['title']}（评分 {item['score']}，{item['feasibility']}）：{item['pros'][0]}",
        }
        for item in evaluations
    ]

    fit = (
        f"推荐策略 {recommended}（{top['score']}分）："
        f"{'跨语言/法务约束已隔离，' if (not same_eco or strong_copyleft_restricted) else '同生态合规可行，'}"
        f"{top['pros'][0]}"
    )

    brief = wf_envelope.build_decision_brief(
        requirement_fit=fit,
        verifiable_evidence=evidences,
        limitations_and_tradeoffs=tradeoffs,
        actionable_options=options,
    )

    return {
        "candidate": cand_name,
        "recommendedStrategy": recommended,
        "sameEcosystem": same_eco,
        "licenseCategory": lic_cat,
        "strategies": evaluations,
        "decision_brief": brief,
    }
