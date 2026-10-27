# wf-retrieval 规范源（维护用）

> **单一真相源**：正文已迁移到 `agents/wf-retrieval.md`，本文件只保留指针，避免两处漂移。
>
> 修改规范时只改 `agents/wf-retrieval.md`；本文件不复制正文。

生效文件：`D:/claude-code/workflow/wf-mode/agents/wf-retrieval.md`

契约摘要（详见生效文件）：

- 单趟闭环，阶段 0–7；
- 账本：`run.json` / `evidence.json` / `result.md`；
- `verified` 必须有来源与原文片段；
- 失败按降级阶梯退，并写入 `run.json.degradation`。
