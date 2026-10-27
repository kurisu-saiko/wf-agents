# 工具：web_search

调用：

```text
python "D:/claude-code/workflow/wf-mode/tools/wf-tool.py" web_search search --query "..." --max-results 5
```

输入：

- `query`：非空字符串；
- `maxResults`：1–20，默认 5。

输出 `data`：

```json
{
  "query": "...",
  "results": [
    {"title": "...", "url": "https://...", "snippet": "..."}
  ]
}
```

规则：

- 主适配器不可用时自动走备选，降级记录在信封 `degradation`；
- 不直接调用底层搜索命令；
- 搜索摘要不能当证据，必须再用 `web_extract` 抓正文。
