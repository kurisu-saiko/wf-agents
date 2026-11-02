# Changelog

## Unreleased

- 开源准备：同步 `/wf-plan`、`/wf-report`、配置模块与集成测试。
- 路径可移植：`runtime` 默认留空，改用 `.wf/config.local.json` 或 `WF_BIN` / `WF_VENV`。
- 清理：不再跟踪 `settings.json` 与 `panel/state.json`，补充忽略规则。
- 工程化：新增 MIT 许可证、依赖清单、CI 与安全/贡献说明。
