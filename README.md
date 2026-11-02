# wf-agents

一个可插拔的 agent + 能力面板，目标是用社区已有项目和工具完成任务，而不是重复造轮子。

`/wf` 在主会话内执行，带两道人工闸口：

```text
能力校准 -> 需求理解 -> 闸口 1（需求确认）
         -> 调研与方案 -> 闸口 2（方案确认） -> 只读报告
```

## 目录

```text
wf-mode/                 插件源码与测试
  commands/              /wf、/wf-plan、/wf-report 协议入口
  agent/                 可选研究后端提示词（模板）
  agents/                渲染生成物（gitignore）
  host/                  宿主适配：haha / claude / dsh + launcher + install
  hooks/                 研究后端权限闸门
  tools/                 wf-tool.py、wf_stage.py、config.py、adapters
  panel/                 Streamlit 能力面板
  contracts/             能力、适配器、信封 schema
  tests/                 集成测试
  capabilities.yaml      能力目录（单一真相源）
  README.md              详细使用说明
```

## 快速开始

```bash
cd wf-mode
pip install -r requirements.txt
python -m pytest tests/integration -q
python tools/wf-tool.py list
python tools/wf-tool.py doctor
```

本机工具路径通过 `.wf/config.local.json` 或环境变量 `WF_BIN` / `WF_VENV` 提供，详见 `wf-mode/README.md`。

## 边界

- 主流程在主会话内执行，不依赖 sidecar。
- 两道人工闸口：需求确认、方案确认。
- 全程只读：不写文件、不装依赖、不部署。
- sidecar 仅作为可选研究后端（`host/launcher.py --mode agent`）。
- 仓库不包含 `.claude.json`、`cc-haha/`、`sessions/`、`projects/`、`telemetry/`、`backups/`、`runtime/`、`legacy/`、`settings.json`、`panel/state.json`、生成物或任何密钥。

## 平台

当前仅在 **Windows** 上验证；macOS/Linux 尚未适配。

## 安全

凭据只注入子进程环境，不落盘、不回显。详见 `SECURITY.md`。

## 许可

MIT，见 `LICENSE`。
