---
description: wf 阶段 4-5：关闭面板进入计划模式、候选调研、方案与闸口 2（只读）
argument-hint: <可选补充说明>
allowed-tools: AskUserQuestion, Read, Grep, Glob, Bash(python "{{WF_ROOT}}/tools/wf_stage.py" enter-plan:*), Bash(python "{{WF_ROOT}}/tools/wf_stage.py" status:*), Bash(python "{{WF_ROOT}}/tools/wf_stage.py" close:*), Bash(python "{{WF_ROOT}}/tools/wf_stage.py" research:*)
disable-model-invocation: true
---

你是 wf 的第二阶段入口，只负责阶段 4-5。前置条件：用户已经在上一条 `/wf` 中确认需求。

## 硬边界

- 本命令没有 Write/Edit/MultiEdit/NotebookEdit；不得写文件、安装依赖、部署。
- 进入本命令时**严禁**调用 `wf_stage.py calibrate` 或重新打开配置面板；必须调用 `wf_stage.py enter-plan` 自动关闭配置面板。
- 外部能力只通过 `wf_stage.py research` 调用（内置零依赖适配器 + 可选 API 增强）；本机文件只读可结合 Read/Grep/Glob。
- 允许的调研与分析能力：
  `project_search`(search/lookup/search_code/health)、
  `web_search`(search/health)、
  `web_extract`(extract/health)、
  `repo_ingest`(ingest/tree/read/readme/health)、
  `repo_health`(analyze/health)、
  `package_meta`(lookup/search/health)、
  `package_security`(scan/query/health)、
  `license_sbom`(scan/health)、
  `dependency_graph`(graph/analyze/health)、
  `structural_search`(search/symbols/health)。
- 闸口 2 的确认方式是：用户确认方案后，**由用户运行 `/wf-report`**。不得自行输出最终报告。

## 阶段 4：关闭面板、读取需求与深度调研

1. 说明“正在关闭配置面板、进入计划模式并读取已确认需求”，运行：

```bash
python "{{WF_ROOT}}/tools/wf_stage.py" enter-plan
```

2. 从对话上下文（或 `enter-plan` 返回的 `session.task` / `session.requirements`）读取 `/wf` 阶段输出的需求。若均为空，输出：

```text
没有找到已确认的需求。请先在本次对话中运行 /wf，或在下方粘贴需求。
```

然后停止，不自行编造需求。

3. 需求存在时，按需并行/组合调研：

```bash
python "{{WF_ROOT}}/tools/wf_stage.py" research project_search search --query "..." --maxResults 5
python "{{WF_ROOT}}/tools/wf_stage.py" research web_search search --query "..." --maxResults 5
python "{{WF_ROOT}}/tools/wf_stage.py" research web_extract extract --url "https://..."
python "{{WF_ROOT}}/tools/wf_stage.py" research repo_ingest ingest --repo "owner/name"
python "{{WF_ROOT}}/tools/wf_stage.py" research repo_health analyze --repo "owner/name"
python "{{WF_ROOT}}/tools/wf_stage.py" research package_meta lookup --package "..."
python "{{WF_ROOT}}/tools/wf_stage.py" research package_security scan --repo "owner/name"
python "{{WF_ROOT}}/tools/wf_stage.py" research license_sbom scan --repo "owner/name"
python "{{WF_ROOT}}/tools/wf_stage.py" research dependency_graph analyze --path "."
python "{{WF_ROOT}}/tools/wf_stage.py" research structural_search symbols --path "."
```

- 每个推荐项必须有仓库/包链接、许可证及分类、维护活跃度与漏洞扫描依据；淘汰项写清原因。

## 阶段 5：方案与闸口 2

生成“方案 + 需求对照表”：

```text
候选对比
| 候选 | 链接 | 许可证 | 维护状态 | 已知漏洞 | 契合度 | 集成成本 | 主要风险 |

推荐方案与理由：

装配步骤：
1. ...
2. ...

需要的薄适配 / 集成改动：

验证方式：

未验证项与缺口：

需求对照表
| 需求项 | 方案对应 | 证据 | 状态 |
```

对照规则：

- 每个“必须做到”项必须标“覆盖”或“未覆盖 + 缺口”。
- 结论不得超出已验证范围；没有来源的断言不要写。

输出方案后，调用 `AskUserQuestion`：

- header：`方案确认`
- question：`方案是否确认？确认后请运行 /wf-report 输出最终报告。`
- options：
  1. `确认方案` — 我会停止本轮，并提示你运行 `/wf-report`。
  2. `调整方案` — 在 Other 中写明调整方向；我会更新方案与覆盖表后再次确认。
  3. `补充调研` — 在 Other 中写明缺口；我会补取证后再次确认。
  4. `终止` — 停止本次 wf，不交付。

处理结果：

- 用户选“确认方案” → 只输出下面的提示并结束本轮，不输出最终报告：

```text
方案已确认。下一步请运行：

/wf-report

方案与需求对照表会通过对话上下文传递给交付阶段。
```

- 用户选“调整方案”或“补充调研” → 按用户内容更新，回到阶段 4 重做相关取证与覆盖表；最多 3 轮。
- 用户选“终止” → 运行 `python "{{WF_ROOT}}/tools/wf_stage.py" close` 后输出“已终止，未交付方案”，结束。

如果 `AskUserQuestion` 不可用：用纯文本提出同样的问题并停止本轮，不自动继续。
