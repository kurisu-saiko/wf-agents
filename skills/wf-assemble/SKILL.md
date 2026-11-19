---
name: wf-assemble
description: >-
  Execute Steps 4-6 of the wf pipeline (Local Integration Contract Design, AST Slice Closure,
  Granular Diff Approval, Safety Checkpoint & Assembly Apply, Closed-Loop Verification & Rollback).
  Enforces Gate 4/5 human approval before modifying files and records provenance in THIRD_PARTY_NOTICES.md.
---

# WF-Assemble：本地对接、安全组装与闭环验证（Steps 4 ~ 6）

用于完成开源项目从“选型与定策略”到“可运行、可追溯、可回滚代码”的工程闭环。

## 强制前置条件

- 确保已通过 **Gate 3**（确定复用策略与选定候选）。可通过 `wf_status(projectPath=".")` 检查 `.wf/decisions/` 账本状态。

## 执行步骤

### Step 4：切片闭包计算与对接契约设计（Gate 4 & Gate 5）

1. **如选择 `CODE_SLICE` 或 `VENDORING`**：
   - 先调用 `wf_slice_closure(sourcePath=..., targetFiles=...)` 验证最小传递依赖闭包完整（`closureComplete=true`）、识别所有外部依赖与导出符号。
2. **设计本地对接契约**：
   - 调用 `wf_contract_design(projectPath=".", strategy=..., candidate=..., adapterName=..., ...)`；
   - 工具会自动生成分块变更预览：
     - **Chunk A**：依赖清单变更（如 `pyproject.toml` / `package.json` / `requirements.txt`）；
     - **Chunk B**：带 SPDX 版权头的切片文件 + `THIRD_PARTY_NOTICES.md` 更新；
     - **Chunk C**：薄 Facade/Adapter 隔离层（不直接污染业务模块）+ 自包含冒烟测试（`tests/test_<name>_smoke.py`）。
3. **Gate 4 & Gate 5 人类批准**：
   - 向用户展示 Adapter 接口边界与各 Chunk 的 unified diff 摘要。
   - 获批后调用 `wf_gate_commit(projectPath=".", gate="GATE_4", status="approved", ...)`。

### Step 5：安全检查点与原子落盘

1. 调用 **`wf_assemble_apply(projectPath=".", contract=..., requireGateApproval=true)`**：
   - 系统自动在 `.wf/checkpoints/<checkpointId>/` 备份所有受影响文件与 Git 状态；
   - 原子写入 Chunk A / B / C 文件并同步登记 `GATE_5` 与 `checkpointId` 到 `.wf/decisions/`。

### Step 6：自动化闭环验证与 Gate 6 验收/回滚

1. 调用 **`wf_verify_run(projectPath=".", contract=..., runProjectTests=false|true)`**：
   - 自动运行 `py_compile` 语法检查与生成的 Adapter 冒烟测试（以及可选项目现有测试回归）。
2. 向用户呈交验证结果与 `decision_brief`，发起 **Gate 6**：
   - **选“验收通过”**：调用 `wf_gate_commit(projectPath=".", gate="GATE_6", status="approved", summary="...")`，保留 `.wf/decisions/ADR-<session>.md` 与 `THIRD_PARTY_NOTICES.md`。
   - **选“一键回滚”**：调用 `wf_checkpoint(action="rollback", projectPath=".", checkpointId=...)` 并更新 `wf_gate_commit(gate="GATE_6", status="rolled_back", ...)`，精准恢复修改并清理新增文件。
