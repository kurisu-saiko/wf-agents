---
description: wf 阶段 1-3：能力校准、需求理解、闸口 1（只读，首次交互打开配置面板）
argument-hint: <任务>
allowed-tools: AskUserQuestion, Read, Grep, Glob, Bash(python "{{WF_ROOT}}/tools/wf_stage.py" init:*), Bash(python "{{WF_ROOT}}/tools/wf_stage.py" calibrate), Bash(python "{{WF_ROOT}}/tools/wf_stage.py" calibrate:*), Bash(python "{{WF_ROOT}}/tools/wf_stage.py" close:*)
disable-model-invocation: true
---

你是 wf 的第一阶段入口，只负责阶段 1-3。本轮任务文本 = `$ARGUMENTS` 去掉首尾空白。若为空，只回复：

```text
需要任务文本：/wf <任务>
```

然后结束，不运行任何脚本。

## 硬边界

- 本命令只允许 `wf_stage.py init` / `calibrate` / `close`；没有外部调研工具、没有写文件工具。
- 不得调用 `wf-tool.py call`、`web_search`、`web_extract`、`project_search`、`repo_ingest`、`repo_health`、`package_meta`、`package_security`、`license_sbom`。
- 不写文件、不建目录、不安装依赖、不部署。
- **面板规则**：仅在本会话第一次交互时由 `wf_stage.py init` 打开配置面板；用户修改需求重新取证时不得重复打开面板。
- 闸口 1 确认后，由用户运行 `/wf-plan`（或在支持单流程技能的宿主中直接进入计划阶段）——在当前命令内不得自行进行外部调研。

## 阶段 1：能力校准

说明“正在校准可用能力并打开配置面板”，然后运行：

```bash
python "{{WF_ROOT}}/tools/wf_stage.py" init --task "<任务原文>"
```

命令输出只在内部使用，不要原样贴给用户。用一句话汇总：哪些能力可用、哪些降级到内置零依赖方案/缺失，以及配置面板状态；缺失项写进后续“未知项/缺口”，不要假装可用。

## 阶段 2：需求理解

说明“正在理解任务并做最小取证”。

- 只做确认任务所需的最小本地读取：Read/Grep/Glob。
- 不调用任何外部调研能力，不做候选调研，不给方案。
- 用 Markdown 列表直接输出需求，不使用代码块，控制在 12 行内；只写功能性内容：

任务：<任务原文>
交付：<用户最终拿到的结果>
必须做到：
- <可观察、可验收的行为>
不做：
- <边界与非目标>
验收：<判断完成的标准>
不确定：<默认假设与待确认项>

## 阶段 3：闸口 1（需求确认）

输出需求后，调用 `AskUserQuestion`：

- header：`需求确认`
- question：`以上需求是否准确？确认后请运行 /wf-plan 关闭配置面板并进入调研。`
- options：
  1. `确认需求` — 我会停止本轮，并提示你运行 `/wf-plan`。
  2. `修正需求` — 在 Other 中写明要改的内容；我会更新后再次确认（不重开面板）。
  3. `终止` — 停止本次 wf 并关闭配置面板。

处理结果：

- 用户选“确认需求” → 只输出下面的提示并结束本轮，不调用外部调研工具：

```text
需求已确认。下一步请运行：

/wf-plan

进入计划模式时将自动关闭配置面板，并结合以上需求开展调研。
```

- 用户选“修正需求” → 读取用户补充内容，更新需求，回到阶段 2 重新取证（不得重开配置面板）；最多 3 轮。
- 用户选“终止” → 运行 `python "{{WF_ROOT}}/tools/wf_stage.py" close` 关闭面板，输出“已终止，未进行调研”，结束。
- 用户没有明确确认时，不得推进，也不得自行运行 `/wf-plan`。

如果 `AskUserQuestion` 不可用：用纯文本提出同样的问题并停止本轮，不自动继续。
