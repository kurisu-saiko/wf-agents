# wf-task-interpret 规范源（维护用）

> **单一真相源**：正文在 `agents/wf-task-interpret.md`，本文件只保留指针。
>
> 修改规范时只改 agent 文件；本文件不复制正文。

生效文件：`D:/claude-code/workflow/wf-mode/agents/wf-task-interpret.md`

定位：

- 介于“显式指定”和“规则兜底”之间；
- 无工具，只做逻辑整理、槽位提取与管线转接；
- 输出纯 JSON 计划；
- 模型层无效时才退回规则兜底。
