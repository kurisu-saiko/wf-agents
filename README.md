# wf-agents

wf-mode 工作流的协作用仓库。`/wf` 现在在主会话内执行，带两道人工闸口（需求确认、方案确认），全程只读。

## 目录

```text
wf-mode/                 实际插件源码（commands、agent、host、hooks、tools、panel、contracts、tests）
wf-mode/README.md        使用说明、协议阶段、安装与测试
```

## 快速开始

```bash
cd wf-mode
python -m pytest tests/integration -q
python tools/wf-tool.py list
python tools/wf-tool.py doctor
```

`/wf <任务>` 的流程：

```text
能力校准 -> 需求卡 -> 闸口 1（需求确认） -> 调研/方案 -> 闸口 2（方案确认） -> 只读报告
```

## 当前边界

- 主流程在主会话内执行，不依赖 sidecar；
- 两道闸口：需求确认、方案确认；
- 全程只读：不写文件、不装依赖、不部署；
- sidecar 仅作为可选研究后端（`host/launcher.py --mode agent`）；
- 不包含 `.claude.json`、`cc-haha/`、`runtime/`、`legacy/`、`projects/`、`telemetry/`、`backups/`、生成物与任何密钥。

## 协作约定

- `wf-mode/commands/wf.md` 定义入口协议与闸口；
- `wf-mode/agent/wf-agent.md` 是可选研究后端提示词；`agents/wf-agent.md` 是生成物，不要手改；
- `wf-mode/contracts/` 是能力/信封契约的唯一真相源；
- 提交前跑 `python -m pytest tests/integration -q`。
