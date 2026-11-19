"""决策导向输出协议（Decision-Oriented Envelope）。

遵循“反失控”铁律 2：以“决策有用性”而非“接口有返回”为验收标准，
每次阶段性决策输出强制包含四要素（Decision Brief）：
1. requirement_fit: 是否命中需求？
2. verifiable_evidence: 证据能否核验（URL / Commit / File / Line / CVE / Test）？
3. limitations_and_tradeoffs: 局限与代价是否说清？
4. actionable_options: 人看完能不能直接拍板？
"""

from __future__ import annotations

from typing import Any


def build_decision_brief(
    *,
    requirement_fit: str,
    verifiable_evidence: list[str],
    limitations_and_tradeoffs: list[str],
    actionable_options: list[dict[str, Any]],
) -> dict[str, Any]:
    """构建结构化决策简报对象。"""
    clean_evidence = [str(item).strip() for item in verifiable_evidence if str(item).strip()]
    clean_tradeoffs = [str(item).strip() for item in limitations_and_tradeoffs if str(item).strip()]
    clean_options: list[dict[str, Any]] = []
    for idx, opt in enumerate(actionable_options):
        if not isinstance(opt, dict):
            continue
        entry = dict(opt)
        entry.setdefault("id", f"opt_{idx + 1}")
        entry["summary"] = str(entry.get("summary") or "").strip()
        if entry["summary"]:
            clean_options.append(entry)

    brief = {
        "requirement_fit": str(requirement_fit or "").strip(),
        "verifiable_evidence": clean_evidence,
        "limitations_and_tradeoffs": clean_tradeoffs,
        "actionable_options": clean_options,
    }
    ok, issues = validate_decision_brief(brief)
    if not ok:
        raise ValueError(f"DecisionBrief 校验失败: {'; '.join(issues)}")
    return brief


def validate_decision_brief(brief: Any) -> tuple[bool, list[str]]:
    """校验决策简报是否完整回答“决策四问”。"""
    issues: list[str] = []
    if not isinstance(brief, dict):
        return False, ["decision_brief 必须是字典对象"]

    fit = str(brief.get("requirement_fit") or "").strip()
    if not fit:
        issues.append("缺少 requirement_fit（是否命中需求）")

    evidence = brief.get("verifiable_evidence")
    if not isinstance(evidence, list) or not [x for x in evidence if str(x).strip()]:
        issues.append("缺少 verifiable_evidence（至少 1 条可核验证据）")

    tradeoffs = brief.get("limitations_and_tradeoffs")
    if not isinstance(tradeoffs, list) or not [x for x in tradeoffs if str(x).strip()]:
        issues.append("缺少 limitations_and_tradeoffs（必须明确局限与代价）")

    options = brief.get("actionable_options")
    if not isinstance(options, list) or len(options) == 0:
        issues.append("缺少 actionable_options（必须提供至少 1 个可直接拍板的选项）")
    else:
        for i, opt in enumerate(options):
            if not isinstance(opt, dict) or not str(opt.get("summary") or "").strip():
                issues.append(f"actionable_options[{i}] 缺少 summary 描述")

    return len(issues) == 0, issues


def attach_decision_brief(envelope: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    """将经过校验的 decision_brief 附加到标准工具信封中。"""
    ok, issues = validate_decision_brief(brief)
    if not ok:
        raise ValueError(f"无法附加无效的 decision_brief: {'; '.join(issues)}")
    out = dict(envelope)
    out["decision_brief"] = brief
    return out
