# 安全说明

## 运行边界

- `/wf` → `/wf-plan` → `/wf-report` 主流程只读：不写文件、不装依赖、不部署。
- 写类能力（如 `scaffold`）只在执行阶段、用户明确批准后使用，默认不进入计划流程。
- 外部能力统一通过 `tools/wf-tool.py` 调用，不直接执行底层命令。

## 凭据处理

宿主 GitHub token 仅用于注入子进程环境，不落盘、不写日志、不回显。读取顺序：

1. `WF_CREDENTIALS`
2. `.wf/config.local.json` 的 `credentials`
3. `~/.claude/.credentials.json`

找不到时静默跳过。仓库不包含任何密钥、OAuth 配置或会话文件。

## 报告漏洞

请通过 GitHub 私有安全公告（Security → Advisories）报告，不要在公开 issue 中粘贴密钥、token 或完整利用细节。

## 已知范围

- 当前仅在 Windows 上验证；其他平台的宿主适配与 CLI 能力尚未验证。
- 第三方 API（Tavily、Exa、Firecrawl、Jina、GitHub）会把查询/仓库信息发送到对应服务，请自行评估数据范围。
