# 贡献指南

## 环境

- Python 3.12（代码需要 3.10+）
- 当前仅在 Windows 上验证
- 安装依赖：`pip install -r wf-mode/requirements.txt`

## 测试

```bash
cd wf-mode
python -m pytest tests/integration -q
```

提交前必须全绿。

## 本地路径

`capabilities.yaml` 的 `runtime.bin` / `runtime.venv` 默认为空。请用 `.wf/config.local.json`（已 gitignore）或环境变量 `WF_BIN` / `WF_VENV` 提供本机路径，不要修改 `capabilities.yaml` 写死个人路径。

## 提交约定

- 不要提交：`.wf/config.local.json`、`settings.json`、`panel/state.json`、`Cache/`、`shell-snapshots/`、`runtime/`、`legacy/`、`agents/wf-agent.md`、任何密钥/凭据。
- 修改协议（`commands/`）、契约（`contracts/`）或能力目录（`capabilities.yaml`）时，同步更新测试。
- 不要手改 `agents/wf-agent.md`（生成物）；改 `agent/wf-agent.md` 后用 `host/common.py` 的 `render_agent()` 重新生成。
- 提交前检查 `git status`，避免把运行时文件带入。
