# project_search

项目发现。Phase 1 使用 GitHub REST API。

## 动作

### search

输入：

```json
{"query": "searxng", "maxResults": 5}
```

输出：

```json
{
  "query": "searxng",
  "candidates": [
    {
      "name": "searxng",
      "fullName": "searxng/searxng",
      "url": "https://github.com/searxng/searxng",
      "description": "...",
      "stars": 12345,
      "updatedAt": "2026-...",
      "license": "AGPL-3.0",
      "archived": false,
      "language": "Python"
    }
  ]
}
```

### lookup

输入：

```json
{"repo": "owner/name"}
```

或：

```json
{"url": "https://github.com/owner/name"}
```

输出单个 candidate。

### health

输出 GitHub 是否带 token；无 token 时公共 API 仍可用。

## 凭据

- `GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_MCP_TOKEN`（可选）

## 边界

- 只读；
- 不 clone、不下载仓库；
- 限流错误映射为 `RATE_LIMIT` / `AUTH_FAILED`。
