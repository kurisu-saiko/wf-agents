---
name: wf-plan
description: >-
  Enter or resume Steps 2-3 (Compliance Audit & 5-Way Reuse Strategy Selection) of the wf pipeline.
  Ensures the config panel is closed, collects verifiable evidence, runs wf_strategy_evaluate,
  and persists Gate 2 / Gate 3 decisions to .wf/decisions/.
---

# WF-Plan：合规评估与 5 选 1 复用策略规划（Steps 2 ~ 3）

当用户在 Gate 1 后分步进入调研与策略设计阶段（`/wf-plan`）时使用。

## 执行步骤

1. **确保进入计划模式且关闭配置面板**：
   - 调用 `wf_enter_plan`（或 `wf_gate_commit(gate="GATE_1", ...)`），**严禁重开配置面板**。
   - 调用 `wf_status(projectPath=".")` 恢复当前需求与账本进度，同时调用 `wf_local_profile(path=".")` 摸清本地技术栈与验证探针。
2. **候选深度核验（Step 2）**：
   - 组合调用 `wf_project_search`、`wf_repo_inspect`、`wf_repo_health`、`wf_license_scan`、`wf_package_security`、`wf_package_meta`。
   - 为用户呈现可核验证据表与局限分析，完成 **Gate 2 确认** 并调用 `wf_gate_commit(projectPath=".", gate="GATE_2", ...)`。
3. **5 选 1 复用策略评估（Step 3）**：
   - 调用 `wf_strategy_evaluate(candidate=..., projectPath=".", intent=...)` 获取量化的策略代价矩阵与 `decision_brief`。
   - 请用户通过 **Gate 3** 在 `PACKAGE_DEP / CODE_SLICE / VENDORING / SIDECAR / PATTERN_REF` 中拍板，并记录到 `wf_gate_commit(projectPath=".", gate="GATE_3", strategy=...)`。
4. **衔接下一步**：
   - 策略拍板后，直接转入 `/wf-assemble`（调用 `wf_slice_closure` / `wf_contract_design`）开始本地对接设计；若用户只需书面归档，转 `/wf-report`。
