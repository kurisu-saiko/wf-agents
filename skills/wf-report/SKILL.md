---
name: wf-report
description: >-
  Export an Architecture Decision Record (ADR) or final read-only evaluation summary
  based on .wf/decisions/ ledger and session evidence, keeping the config panel closed.
---

# WF-Report：导出决策报告与 ADR 归档

当用户只需输出只读调研评估摘要，或在组装前后查看审计归档时使用。

## 执行步骤

1. 调用 `wf_enter_report` 与 `wf_status(projectPath=".")`，确保配置面板已关闭，并读取 `.wf/decisions/<sessionId>.json` 及已生成的 `ADR-<sessionId>.md` 审计轨迹。
2. 基于已核验证据整理结构化报告（需求匹配、候选对比、合规/健康度结论、复用策略代价矩阵、本地对接契约与验证结果、未验证项与缺口）。
3. 明确区分当前状态（**尚未写盘的只读报告** vs **已完成组装并通过 Gate 6 验收的 ADR 归档**），并附带检查点/回滚指引或下一步启动组装选项。
