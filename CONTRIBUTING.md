# 贡献指南

## 环境

- Python 3.10+（核心仅需标准库 + `PyYAML`；开发测试建议使用虚拟环境安装 `pytest` 与 `jsonschema`）
- 安装依赖：`pip install -r wf-mode/requirements.txt`

## 四层测试

```bash
cd wf-mode
python -m pytest tests/integration -q
```

提交前必须全绿。测试目录涵盖：
- `test_tier1_unit_engine.py`：DecisionBrief、5 选 1 策略评分、AST 切片闭包与远程切片、SPDX 合规头。
- `test_tier2_pipeline_gates.py`：`.wf/decisions/` 账本流转、Gate 4/5 强拦截、安全检查点与一键回滚。
- `test_tier3_live_mcp_and_hosts.py`：24 工具 Stdio MCP 握手与全阶段调用。
- `test_tier4_eval_benchmarks.py`：Python / TypeScript / JavaScript / Sidecar / PatternRef 黄金组装与无污染回滚评估。

## 本地路径

`capabilities.yaml` 的 `runtime.bin` / `runtime.venv` 默认为空。请通过内置配置面板或 `WF_DATA_DIR`、`WF_BIN`、`WF_VENV` 提供本机路径，不要把个人路径硬编码提交。

## 提交约定

- 唯一真源：所有跨宿主工作流提示词与规则统一维护在仓库根目录 `skills/`（`wf`、`wf-plan`、`wf-assemble`、`wf-report`）与 `rules/AGENTS.md`。
- 修改契约（`wf-mode/contracts/`）、能力目录（`wf-mode/capabilities.yaml`）或 MCP 工具列表时，必须同步更新测试与文档。
- 提交前检查 `git status`，不要把 `.wf/config.local.json`、`settings.json`、`panel/state.json`、`runtime/`、`.venv/` 或任何密钥带入提交。
