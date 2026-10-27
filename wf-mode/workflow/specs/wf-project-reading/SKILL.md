# wf-project-reading 规范源（维护用）

> **单一真相源**：正文已迁移到 `agents/wf-project-reading.md`，本文件只保留指针，避免两处漂移。
>
> 修改规范时只改 `agents/wf-project-reading.md`；本文件不复制正文。

生效文件：`D:/claude-code/workflow/wf-mode/agents/wf-project-reading.md`

契约摘要（详见生效文件）：

- 单趟闭环，阶段 0–7；
- 账本：`run.json` / `evidence.json` / `result.md`；
- `verified` 必须有 `file:line`；
- 未覆盖区域必须写入 `uncovered`。
