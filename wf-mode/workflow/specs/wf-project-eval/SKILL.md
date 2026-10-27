# wf-project-eval 规范源（维护用）

> **单一真相源**：正文已迁移到 `agents/wf-project-eval.md`，本文件只保留指针，避免两处漂移。
>
> 修改规范时只改 `agents/wf-project-eval.md`；本文件不复制正文。

生效文件：`D:/claude-code/workflow/wf-mode/agents/wf-project-eval.md`

契约摘要（详见生效文件）：

- 单趟闭环，阶段 0–7；
- 账本：`run.json` / `evidence.json` / `result.md`；
- `included` / `excluded` 必须有来源，`excluded` 必须有原因；
- 封装工具优先，底层命令只作降级档并留痕。
