---
name: wf
description: >-
  Run the evidence-first open-source discovery, codebase analysis, security/license audit,
  and adoption planning workflow with two human confirmation gates and automatic config panel
  lifecycle (opens once on first interaction, closes automatically when entering plan mode).
  Use when the user invokes /wf or asks to evaluate, compare, audit, or adopt open-source
  projects/libraries instead of reinventing the wheel.
---

# WF：开源探索、项目分析与装配工作流

核心目标：**用真实证据发现、评估并装配成熟的开源方案或现有库，避免盲目造轮子。**

本技能兼容所有支持 MCP 或终端命令的 Agent（Antigravity、Claude Code、Cursor、Codex、Gemini CLI、OpenCode 等）：
- **优先使用 MCP 工具**（`wf_start`、`wf_enter_plan`、`wf_enter_report`、`wf_*`）；
- 若宿主未挂载 MCP，等价调用终端命令 `python "<WF_ROOT>/tools/wf_stage.py" ...`；
- **增强而不捆绑**：将 `wf_*` 的结构化分析能力与宿主自身的只读工具（`read_file` / `Read` / `Grep` / `Glob` / `search_web` 等）结合使用。

## 面板与阶段硬规则

1. **配置面板生命周期（严格执行）**：
   - **仅首次交互打开**：第 1 阶段调用一次 `wf_start`（或 `wf_stage.py init --task "..."`），在第一次交互时自动开启配置面板。
   - **修正需求时不重开**：若用户在闸口 1 选择修改需求，**不要**再次调用 `wf_start` 或重新弹窗。
   - **进入计划模式自动关闭**：一旦用户确认需求，进入计划/调研阶段前**必须立即调用 `wf_enter_plan`**（或 `wf_stage.py enter-plan`），自动关闭配置面板并解锁全部外部调研工具。
2. **全程默认只读**：在用户未明确授权落盘/安装前，不修改工作区源码、不安装依赖、不部署服务。
3. **无证据不下结论**：仓库链接、Star 数、许可证类别、CVE 漏洞、文件路径与行号必须来自实际工具返回。

---

## 阶段 1：能力校准与需求理解（`init`）

1. 向用户简短说明“正在初始化 wf 并校准可用能力”。
2. 调用 **`wf_start`**（传入 `task`，`openPanel: true`；或 CLI：`python "<WF_ROOT>/tools/wf_stage.py" init --task "<任务>"`）。
   - 若用户未提供任务文本，只礼貌提示 `请告诉我你想调研或评估的任务，例如：/wf <任务描述>` 后结束本轮。
   - 用 **1 句话**概括当前能力状态（哪些已就绪、哪些降级到零密钥兜底、配置面板是否已开启）；不要把原始 JSON 贴给用户。
3. **快速理解本地语境（可选，仅当涉及当前项目时）**：
   - 可调用 `wf_project_analyze` / `wf_structural_search` / `wf_repo_inspect(path=...)` 或宿主只读文件工具，快速识别当前项目技术栈、语言与架构约束。
   - 此阶段**不要**开始搜索开源候选或输出技术方案。
4. 输出结构紧凑、可直接验收的 **需求确认卡**（Markdown 列表，10–14 行以内）：
   - **任务目标**：一句话概括要解决的问题
   - **预期交付**：最终提供的对比、装配方案与风险报告
   - **必须做到（Must）**：2–4 条可观察、可验收的行为或硬条件（如平台、语言、许可要求）
   - **非目标（不做）**：本次明确排除的范围
   - **验收标准**：如何判定方案可落地
   - **默认假设与待确认**：信息不足时的合理假设

## 闸口 1：需求确认

调用宿主的交互确认工具（Antigravity `ask_question` / Claude Code `AskUserQuestion`；若不可用，输出清晰的 1/2/3 编号纯文本选项并停止本轮）：

- **问题**：`以上需求理解是否准确？确认后我将关闭配置面板并正式进入调研与方案设计。`
- **选项**：
  1. `确认需求，进入计划与调研`
  2. `补充或修改需求`
  3. `终止工作流`

处理分支：
- **选 2（补充/修改）**：结合用户补充更新需求卡，**不要**重开配置面板，重新发起闸口 1 确认。
- **选 3（终止）**：调用 `wf_close`（关闭面板），告知用户已终止并结束。
- **选 1（确认）**：**无需用户手动再敲 `/wf-plan`**，直接进入下方阶段 2！

---

## 阶段 2：深度调研、分析与装配方案（`plan`）

1. **立即调用 `wf_enter_plan`**（传入确认后的 `requirements`；或 CLI：`python "<WF_ROOT>/tools/wf_stage.py" enter-plan`）。
   - 这一步会**自动关闭配置面板**并解锁所有外部调研能力。
2. **多维度真实取证**（按任务需要组合调用，优先并行）：
   - **候选发现**：`wf_project_search(action="search", ...)`、`wf_web_search(...)`、`wf_package_meta(action="search", ...)`；
   - **深入读库**：`wf_repo_inspect(action="ingest" | "tree" | "read" | "readme", repo=...)`、`wf_project_search(action="search_code", ...)`、`wf_web_extract(url=...)`；
   - **健康度与风险审计**：`wf_repo_health(repo=...)`、`wf_license_scan(repo=... / path=...)`、`wf_package_security(action="scan" | "query", ...)`、`wf_package_meta(action="lookup", ...)`；
   - **本地契合度分析**：`wf_project_analyze(path=...)`、`wf_structural_search(action="symbols" | "search", path=...)` 或宿主原生只读工具。
3. **输出方案对比与装配计划**：
   - **候选对比表**（项目/包、链接、许可证与商用分类、维护活跃度、已知 CVE/风险、契合度、集成成本）
   - **推荐方案与淘汰理由**（明确为什么选 A 不选 B）
   - **可落地的装配步骤**（具体到依赖、模块衔接点、配置要点）
   - **需要自写的薄适配边界**（控制在最小胶水层）
   - **验证方式**（装完后如何验证通过）
   - **需求对照表**（逐条对应阶段 1 的每项 Must：`覆盖` / `部分覆盖` / `未覆盖 + 缺口`）
   - **未验证项与缺口**（坦诚列出未测到的部分）

## 闸口 2：方案确认

调用交互确认工具（或清晰纯文本选项并暂停）：
- **问题**：`以上方案与需求对照是否确认？确认后将生成最终交付报告。`
- **选项**：
  1. `确认方案，生成最终报告`
  2. `调整方案或补充对比`
  3. `终止工作流`

处理分支：
- **选 2**：按用户意见补充调研并更新方案与对照表，再次确认。
- **选 3**：调用 `wf_close`，告知已终止，结束。
- **选 1**：直接进入阶段 3！

---

## 阶段 3：最终交付报告（`report`）

1. 调用 **`wf_enter_report`**（传入方案摘要；或 CLI：`python "<WF_ROOT>/tools/wf_stage.py" enter-report`），确保面板已关闭且状态归档。
2. 基于已核实证据输出结构清晰、可直接执行的**最终调研与装配报告**（包含：任务摘要、候选对比、最终选型与理由、分步装配清单、薄适配点、安全与许可审计结论、验证清单、需求覆盖表、未验证项与缺口）。
3. 末尾注明本次工作流为**只读分析（未改动工作区代码、未安装依赖）**，并自然提示下一步选项：
   - 如需我直接按该方案开始实施改造，请回复确认；
   - 或如需把本报告导出为 Markdown 文档，也可以直接告诉我路径。
