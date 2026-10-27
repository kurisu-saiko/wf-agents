# web_search

通用网页搜索适配器。Tavily 主，Exa 备。

## 动作

### search

输入：

```json
{"query": "非空字符串", "maxResults": 5}
```

输出：

```json
{
  "query": "原始查询",
  "results": [
    {"title": "标题", "url": "https://...", "snippet": "摘要"}
  ]
}
```

### health

输入：无。输出：

```json
{"ok": true, "provider": "tavily", "configured": true, "checkedAt": "..."}
```

## 凭据

- `TAVILY_API_KEY` 或 `TAVILY`
- `EXA_API_KEY` 或 `EXA`

两个都没有时返回 `AUTH_MISSING`，不会静默返回空结果。

## 失败

| 情况 | 错误码 | 是否降级 |
|---|---|---|
| 无密钥 | `AUTH_MISSING` | 是 |
| 401/403 | `AUTH_FAILED` | 是 |
| 429 | `RATE_LIMIT` | 是 |
| 超时 | `TIMEOUT` | 是 |
| 5xx | `UPSTREAM_ERROR` | 是 |

## 边界

- 只读，不写文件；
- 不记录请求头；
- 搜索摘要只是线索，不是证据。
