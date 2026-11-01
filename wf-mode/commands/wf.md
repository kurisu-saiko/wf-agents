---
description: wf 项目探索与组装入口（主会话交互式，两道人工闸口）
argument-hint: <任务>
allowed-tools: AskUserQuestion, Read, Grep, Glob, Bash(python "{{WF_ROOT}}/tools/wf-tool.py":*), Bash(python "{{WF_ROOT}}/host/launcher.py":*), mcp__plugin_office-github_service__search_repositories, mcp__plugin_office-github_service__search_code, mcp__plugin_office-github_service__get_file_contents, mcp__plugin_office-github_service__list_commits, mcp__plugin_office-github_service__list_branches, mcp__plugin_office-github_service__list_releases, mcp__plugin_office-github_service__get_latest_release, mcp__plugin_office-github_service__list_tags, mcp__plugin_office-github_service__get_commit, mcp__plugin_office-github_service__issue_read, mcp__plugin_office-github_service__list_issues, mcp__plugin_office-github_service__pull_request_read, mcp__plugin_office-github_service__list_pull_requests, mcp__plugin_office-github_service__search_issues, mcp__plugin_office-github_service__search_pull_requests, mcp__plugin_office-github_service__list_repository_collaborators
disable-model-invocation: true
---

你是 wf 的入口协议。本轮在主会话内执行，严格按下面的阶段推进。

每进入一个阶段，先用一句话说明当前阶段与正在做的事，然后再调用工具。用户必须能实时看到过程，不要憋到最后一次性输出。

本轮任务文本 = `$ARGUMENTS` 去掉首尾空白。若为空，只回复：

```text
需要任务文本：/wf <任务>
```

然后结束，不运行任何脚本。

## 只读边界（全程有效）

- 不写文件、不建目录、不安装依赖、不部署；不调用 Write/Edit/MultiEdit/NotebookEdit。
- 只允许通过 `Bash` 运行 `{{WF_ROOT}}/tools/wf-tool.py`；仅在需要可选深度研究后端时运行 `{{WF_ROOT}}/host/launcher.py --mode agent`。
- 不使用 `host/launcher.py` 的 `--mode direct` 或 `--mode auto`。
- 需要仓库/目录信息时，直接用 Read/Grep/Glob 或 `wf-tool call`，不要走关键词直连。
- 外部能力只通过 `wf-tool call` 调用；GitHub 只使用只读 MCP 工具。
- 失败先按能力目录的主备链降级；主备都失败就写明缺口，不换写法绕过。

## 阶段 1：能力校准

说明“正在校准可用能力”，然后运行（命令输出只在内部使用，不要原样贴给用户）：

```bash
python "{{WF_ROOT}}/tools/wf-tool.py" doctor
python "{{WF_ROOT}}/tools/wf-tool.py" list
```

用一句话汇总：哪些能力可用、哪些缺失。缺失项写进后续“未知项/缺口”，不要假装可用。

## 阶段 2：需求理解

说明“正在理解任务并做最小取证”。

- 只做确认任务所需的最小读取：Read/Grep/Glob；必要时用 `wf-tool call` 或只读 MCP。
- 不要在这一阶段做完整的候选调研，也不要给出方案。
- 生成下面格式的“需求卡”：

```text
任务原文：
成品形态：
功能 / 可观察行为：
Must：
Should：
边界与非目标：
验收标准：
未知项：
已核实证据（路径/URL）：
```

规则：

- Must/Should 必须是可观察、可验收的行为；不要写“好用”“高质量”这类无法验收的词。
- 信息不足时，给出默认假设并列入“未知项”，不要连续追问。
- 已核实证据必须真的有来源；没有来源的写“未核实”。

## 阶段 3：闸口 1（需求确认）

输出需求卡后，调用 `AskUserQuestion`：

- header：`需求确认`
- question：`需求卡是否准确？确认后我才会开始候选调研与方案设计。`
- options：
  1. `确认，开始调研` — 按当前需求卡执行，不再改动 Must 与验收标准。
  2. `修正需求卡` — 在 Other 中写明要改的字段；我会更新后再次确认。
  3. `终止` — 停止本次 wf，不继续调研。

处理结果：

- 用户选“确认，开始调研” → 进入阶段 4。
- 用户选“修正需求卡” → 读取用户补充内容，更新需求卡，回到阶段 2 重新取证；最多 3 轮。
- 用户选“终止” → 输出“已终止，未进行调研”，结束。
- 用户没有明确确认时，不得自行推进。

如果 `AskUserQuestion` 不可用：用纯文本提出同样的问题并停止本轮，不自动继续。

## 阶段 4：调研与方案

说明“需求已确认，正在调研候选与验证证据”。只有这样才允许做候选调研。

- 候选发现：`project_search search`、`web_search search`、只读 GitHub MCP。
- 读取理解：`web_extract extract`、`repo_ingest ingest`、`structural_search search`、`dependency_graph graph`、Read/Grep/Glob。
- 硬门槛：许可证、维护状态、归档、最近提交/发布、issue 响应；许可证不明时不得下“可直接用”的结论。
- 每个推荐项必须有仓库链接、许可证、维护状态依据；淘汰项写清原因。
- 生成“方案 + 需求覆盖表”：

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

需求覆盖表
| 需求项 | 方案对应 | 证据 | 状态 |
```

覆盖表规则：

- 每个 Must 必须标“覆盖”或“未覆盖 + 缺口”。
- 有 Must 未覆盖时，必须明确说明，不能声称方案已完成。
- 结论不得超出已验证范围；没有来源的断言不要写。

## 阶段 5：闸口 2（方案确认）

输出方案与覆盖表后，调用 `AskUserQuestion`：

- header：`方案确认`
- question：`方案是否确认？确认后我只输出报告，不落盘。`
- options：
  1. `确认，交付报告` — 按当前方案输出最终报告。
  2. `调整方案` — 在 Other 中写明调整方向；我会更新方案与覆盖表后再次确认。
  3. `补充调研` — 在 Other 中写明缺口；我会补取证后再次确认。
  4. `终止` — 停止本次 wf，不交付。

处理结果：

- 用户选“确认，交付报告” → 进入阶段 6。
- 用户选“调整方案”或“补充调研” → 按用户内容更新，回到阶段 4 重做相关取证与覆盖表；最多 3 轮。
- 用户选“终止” → 输出“已终止，未交付方案”，结束。
- 用户没有明确确认时，不得输出最终报告。

## 阶段 6：交付

只输出最终文本报告，不再调用工具。报告包含：

1. 任务与需求卡摘要；
2. 候选对比；
3. 推荐方案与理由；
4. 装配步骤；
5. 需要的薄适配 / 集成改动；
6. 验证方式；
7. 需求覆盖表；
8. 未验证项与缺口；
9. 只读声明。

结尾固定写：

```text
本次 wf 为只读流程，未写入任何文件。如需落盘、安装或部署，请在普通会话中执行，或明确授权后再进行。
```
