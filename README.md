# wf-agents

wf-mode 工作流的协作用仓库。当前包含 Phase 1 内核、3 个 Tier 1 适配器、`wf-retrieval/verify` 管线与集成测试。

## 目录

```text
wf-mode/                实际工作流资产（agents、workflows、contracts、tools、pipelines、tests）
docs/                   计划、第一阶段记录、历史交接说明
docs/HANDOFF-v1.md      历史交接文档；当前权威契约以 wf-mode/contracts/ 为准
```

## 快速开始

```bash
cd wf-mode
python -m pytest tests/integration -q
python tools/wf-tool.py list
python tools/wf-tool.py health
```

## 当前边界

- 只实现 1 条管线：`wf-retrieval/verify`；
- 只实现 3 个能力槽：`web_search`、`web_extract`、`project_search`；
- `ledger` / `render_prompt` / `gates` 目前是 `tools/mocks/` 占位，真实模块交付后放到 `tools/` 即可替换；
- 不包含 `cc-haha`、`.claude.json`、`backups`、`sessions`、`projects`、`.wf/runs`、任何密钥。

## 协作约定

- `wf-mode/contracts/` 是契约唯一真相源；
- 接口改动先提 `CHANGE-REQUEST.md`，确认后再实现；
- 外部开发者从 `wf-mode/` 开始，不要改 `wf-mode/credential` 相关本地配置；
- 提交前跑 `python -m pytest tests/integration -q`。
