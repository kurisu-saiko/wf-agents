---
name: wf-plan
description: >-
  Enter or resume Stage 2 (Plan & Deep Research Mode) of the wf workflow. Automatically closes
  the configuration panel, reads confirmed requirements from session/context, conducts multi-source
  candidate & risk research, and proposes an adoption plan for Gate 2 confirmation.
---

# WF-Plan：进入计划模式与深度调研

当用户明确运行 `/wf-plan` 或从分步工作流继续进入第 2 阶段时使用。

## 执行步骤

1. **立即进入计划模式并关闭面板**：
   - 调用 `wf_enter_plan`（或 CLI：`python "<WF_ROOT>/tools/wf_stage.py" enter-plan`），**严禁再调用 `wf_start` 或重新打开配置面板**。
   - 同时可调用 `wf_status` 恢复会话中保存的 `task` 与 `requirements`（若对话历史已包含需求卡则以对话为准）。
   - 若上下文与 `wf_status` 中均没有任何需求信息，礼貌提示用户先运行 `/wf <任务>` 或直接粘贴需求，然后停止。
2. **多维度深度调研与取证**：
   - 结合 `wf_project_search`、`wf_web_search`、`wf_web_extract`、`wf_repo_inspect`、`wf_repo_health`、`wf_package_meta`、`wf_package_security`、`wf_license_scan`、`wf_project_analyze`、`wf_structural_search` 与宿主只读搜索/读取工具；
   - 核实每个推荐候选的真实链接、许可证类别、近 30/90 天提交活跃度、最新版本及 OSV 漏洞状态；
   - 检查候选与当前本地项目的依赖与架构兼容性。
3. **输出方案与需求对照表**：
   - 候选对比表、推荐方案与理由、分步装配清单、薄适配边界、验证方式、需求覆盖对照表、未验证项与缺口。
4. **闸口 2（方案确认）**：
   - 使用交互提问工具请用户确认：`确认方案，生成最终报告` / `调整或补充调研` / `终止`。
   - 确认后直接调用 `wf_enter_report` 并输出最终报告（或按用户的 `/wf-report` 要求交付），不擅自写文件。
