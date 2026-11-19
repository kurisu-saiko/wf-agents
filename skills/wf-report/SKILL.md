---
name: wf-report
description: >-
  Deliver Stage 3 (Final Read-Only Report) of the wf workflow based on confirmed requirements
  and plan from context or wf_status, ensuring the configuration panel stays closed.
---

# WF-Report：输出最终只读交付报告

当用户在分步模式下调用 `/wf-report` 时使用。

## 执行步骤

1. 调用 `wf_enter_report`（或 `python "<WF_ROOT>/tools/wf_stage.py" enter-report`），确保配置面板已关闭并读取会话记录；同时参考当前对话中已确认的需求卡、候选对比与方案。
2. 若对话与会话记录中均无已确认方案，提示用户先运行 `/wf` 与 `/wf-plan`，不要凭空编造。
3. 按清晰结构输出最终报告（任务摘要、候选对比、推荐选型与理由、分步装配步骤、薄适配边界、安全与许可审计结论、验证方式、需求覆盖表、未验证项与缺口）。
4. 保持只读，末尾声明未修改工作区或安装依赖，并询问是否需要进一步实施或导出报告文件。
