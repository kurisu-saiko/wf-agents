---
name: wf
description: >-
  Run the 6-step evidence-first Open-Source Reuse & Engineering Assembly Pipeline
  (Discovery -> Audit -> 5-Way Strategy -> Local Adapter Contract -> Safe Assembly -> Verification/Rollback)
  with explicit human confirmation gates and automatic config panel lifecycle.
  Use when the user invokes /wf or asks to discover, evaluate, or assemble open-source projects into a local codebase.
---

# WF：人机协同的开源复用与工程组装流水线（Open-Source Reuse & Assembly Pipeline）

核心定位：**不止输出调研报告，而是以真实证据、合规审查、适配本地架构与安全回滚为基础，把网络上的优秀开源项目安全组装到本地仓库并跑通验证。**

全流程拆解为“两条半链路”与 **6 个人类闸口（Gate 1 ~ Gate 6）**：

```text
[前半段：证据与决策引擎（只读）]
1. 发现候选 ──► [Gate 1: 需求与选型确认] ──► 2. 合规与健康评估 ──► [Gate 2: 准入确认]
──► 3. 5选1复用策略评估 ──► [Gate 3: 策略拍板]

[后半段：本地工程组装闭环（受控写盘）]
──► 4. 本地画像与对接契约 ──► [Gate 4: 契约评审] ──► [Gate 5: 分块 Diff 批准]
──► 5. 检查点快照与安全落盘 ──► 6. 闭环验证 ──► [Gate 6: 验收归档或一键回滚]
```

## 铁律

1. **配置面板生命周期（严格执行）**：
   - **仅首次交互打开**：启动时调用一次 `wf_start(task=..., openPanel=true)`。
   - **修正需求不重开**：Gate 1 修改补充需求时**严禁**再次调用 `wf_start` 或重新弹窗。
   - **过闸自动关闭**：一旦 Gate 1 获批，调用 `wf_gate_commit(gate="GATE_1", ...)` 或 `wf_enter_plan` 时自动关闭面板并解锁后续工具。
2. **决不越闸写盘（Human-in-the-Loop）**：
   - 未经用户批准 Gate 4 / Gate 5，绝对不向工作区写入源码或修改依赖配置；
   - 每个重大决策均通过 `wf_gate_commit` 写入项目 `.wf/decisions/<sessionId>.json` 与 `ADR-<sessionId>.md`。
3. **决策导向四问（Decision Brief）**：
   - 每次给用户拍板的输出必须回答：是否命中需求？证据能否核验（URL/Commit/License/CVE/LOC）？局限与代价是否说清？可选动作是什么？

---

## 第一步：初始化与本地画像（`init` -> Gate 1）

1. 调用 `wf_start(task="<任务描述>", openPanel=true)`；用 1 句话概括当前可用能力与面板状态。
2. 如当前处于本地工程仓库，调用 **`wf_local_profile(path=".")`** 与 `wf_project_analyze(path=".")`，识别本地主语言、包管理器、`src/flat` 布局、`adapterDir` 与测试探针（**保持只读**）。
3. 紧凑呈现 **需求与本地约束卡**，使用交互确认工具请求 **Gate 1 确认**：
   - 选项：`1. 确认需求并关闭面板，开始发现与评估候选` / `2. 修改或补充需求` / `3. 终止工作流`。
   - 选 1 后调用 **`wf_gate_commit(projectPath=".", gate="GATE_1", status="approved", summary="...")`**，自动关闭面板并进入第二步。

## 第二步：候选发现与合规/健康评估（Steps 1~2 -> Gate 2）

1. 并行调用：`wf_project_search`、`wf_web_search`、`wf_package_meta`、`wf_repo_inspect`、`wf_repo_health`、`wf_license_scan`、`wf_package_security`。
2. 呈现横向对比矩阵（许可证分类、近 30/90 天维护健康度、已知 OSV CVE、契合度与局限），发起 **Gate 2 准入确认**：选定候选目标并批准法务/安全准入。
3. 用户拍板后调用 **`wf_gate_commit(projectPath=".", gate="GATE_2", status="approved", selectedCandidate="...", evidence=[...])`**。

## 第三步：5 选 1 复用策略定案（Step 3 -> Gate 3）

1. 调用 **`wf_strategy_evaluate(candidate=..., projectPath=".", intent=...)`**，从 5 种形态评估得分与代价：
   - `PACKAGE_DEP`（包依赖安装）
   - `CODE_SLICE`（代码切片最小 AST 闭包抽取）
   - `VENDORING`（整库源码内嵌）
   - `SIDECAR`（跨语言或隔离伴生服务）
   - `PATTERN_REF`（净室模式参考重写）
2. 结合返回的 `decision_brief` 向用户呈交 **Gate 3 策略选票**。用户拍板后调用 **`wf_gate_commit(gate="GATE_3", strategy="...", rationale="...")`**。

## 第四步~第六步：对接契约、分块落盘与闭环验证（Steps 4~6）

- 若用户选择**仅需只读评估报告/ADR**：调用 `wf_enter_report` 或 `/wf-report` 导出决策结论。
- 若用户继续**工程组装落地**：按 `/wf-assemble`（`skills/wf-assemble/SKILL.md`）推进：
  1. **Step 4（契约与切片计算）**：如选 `CODE_SLICE`，先调 `wf_slice_closure` 计算最小传递依赖闭包；再调 `wf_contract_design` 生成 Thin Adapter 隔离层、SPDX 头、`THIRD_PARTY_NOTICES.md`、`smoke_test` 与分块 unified diff（**Gate 4 / Gate 5 确认**）。
  2. **Step 5（安全检查点与写盘）**：提交 `GATE_4` / `GATE_5` 后调用 `wf_assemble_apply`，自动在 `.wf/checkpoints/` 备份并在本仓库原子写入分块变更。
  3. **Step 6（闭环验证或回滚）**：调用 `wf_verify_run` 运行语法编译与冒烟测试；发起 **Gate 6**，通过则 `wf_gate_commit(gate="GATE_6")`，不满意则调 `wf_checkpoint(action="rollback")` 一键恢复原状。
