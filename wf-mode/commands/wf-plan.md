---
description: wf 阶段 4-5：候选调研、方案、闸口 2（只读）
argument-hint: <可选补充说明>
allowed-tools: AskUserQuestion, Read, Grep, Glob, Bash(python "{{WF_ROOT}}/tools/wf_stage.py" calibrate), Bash(python "{{WF_ROOT}}/tools/wf_stage.py" calibrate:*), Bash(python "{{WF_ROOT}}/tools/wf_stage.py" research:*), mcp__plugin_office-github_service__search_repositories, mcp__plugin_office-github_service__search_code, mcp__plugin_office-github_service__get_file_contents, mcp__plugin_office-github_service__list_commits, mcp__plugin_office-github_service__list_branches, mcp__plugin_office-github_service__list_releases, mcp__plugin_office-github_service__get_latest_release, mcp__plugin_office-github_service__list_tags, mcp__plugin_office-github_service__get_commit, mcp__plugin_office-github_service__issue_read, mcp__plugin_office-github_service__list_issues, mcp__plugin_office-github_service__pull_request_read, mcp__plugin_office-github_service__list_pull_requests, mcp__plugin_office-github_service__search_issues, mcp__plugin_office-github_service__search_pull_requests, mcp__plugin_office-github_service__list_repository_collaborators
disable-model-invocation: true
---

你是 wf 的第二阶段入口，只负责阶段 4-5。前置条件：用户已经在上一条 `/wf` 中确认需求。

## 硬边界

- 本命令没有 Write/Edit/MultiEdit/NotebookEdit；不得写文件、安装依赖、部署。
- 外部能力只通过 `wf_stage.py research` 调用；不得直接调用底层命令或自写脚本。
- GitHub 只使用只读 MCP 工具。
- 只允许这些调研能力：
  `project_search`(search/lookup/health)、`web_search`(search/health)、`web_extract`(extract/health)、`repo_ingest`(ingest/health)、`structural_search`(search/health)、`dependency_graph`(graph/health)。
- 闸口 2 的确认方式是：用户确认方案后，**由用户手动运行 `/wf-report`**。你不得自行输出最终报告，也不得自行运行 `/wf-report`。
- 失败先按能力目录的主备链降级；主备都失败就写明缺口，不换写法绕过。

## 阶段 4：确认上下文与调研

1. 说明“正在读取已确认的需求”，先运行：

```bash
python "{{WF_ROOT}}/tools/wf_stage.py" calibrate
```

2. 从对话上下文读取 `/wf` 阶段输出的需求。若找不到，输出：

```text
没有找到已确认的需求。请先在本次对话中运行 /wf，或在下方粘贴需求。
```

然后停止，不自行编造需求。

3. 需求存在时，按需调研。示例：

```bash
python "{{WF_ROOT}}/tools/wf_stage.py" research project_search search --query "..." --maxResults 5
python "{{WF_ROOT}}/tools/wf_stage.py" research web_search search --query "..." --maxResults 5
python "{{WF_ROOT}}/tools/wf_stage.py" research web_extract extract --url "https://..."
python "{{WF_ROOT}}/tools/wf_stage.py" research repo_ingest ingest --repo "owner/name"
python "{{WF_ROOT}}/tools/wf_stage.py" research structural_search search --pattern "def $A($$$)" --lang python --path "."
python "{{WF_ROOT}}/tools/wf_stage.py" research dependency_graph graph --path "."
```

- 候选发现：`project_search search`、`web_search search`、只读 GitHub MCP。
- 读取理解：`web_extract extract`、`repo_ingest ingest`、`structural_search search`、`dependency_graph graph`、Read/Grep/Glob。
- 硬门槛：许可证、维护状态、归档、最近提交/发布、issue 响应；许可证不明时不得下“可直接用”的结论。
- 每个推荐项必须有仓库链接、许可证、维护状态依据；淘汰项写清原因。

## 阶段 5：方案与闸口 2

生成“方案 + 需求对照表”：

```text
候选对比
| 候选 | 链接 | 许可证 | 维护状态 | 契合度 | 集成成本 | 主要风险 |

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
- 有“必须做到”项未覆盖时，必须明确说明，不能声称方案已完成。
- 结论不得超出已验证范围；没有来源的断言不要写。

输出方案后，调用 `AskUserQuestion`：

- header：`方案确认`
- question：`方案是否确认？确认后请手动运行 /wf-report 输出最终报告。`
- options：
  1. `确认方案` — 我会停止本轮，并提示你手动运行 `/wf-report`。
  2. `调整方案` — 在 Other 中写明调整方向；我会更新方案与覆盖表后再次确认。
  3. `补充调研` — 在 Other 中写明缺口；我会补取证后再次确认。
  4. `终止` — 停止本次 wf，不交付。

处理结果：

- 用户选“确认方案” → 只输出下面的提示并结束本轮，不输出最终报告：

```text
方案已确认。本命令不输出最终交付，下一步请手动运行：

/wf-report

方案与需求对照表会通过对话上下文传递给交付阶段。
```

- 用户选“调整方案”或“补充调研” → 按用户内容更新，回到阶段 4 重做相关取证与覆盖表；最多 3 轮。
- 用户选“终止” → 输出“已终止，未交付方案”，结束。
- 用户没有明确确认时，不得输出最终报告，也不得自行运行 `/wf-report`。

如果 `AskUserQuestion` 不可用：用纯文本提出同样的问题并停止本轮，不自动继续。
