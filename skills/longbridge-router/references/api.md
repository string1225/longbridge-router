# 消费接口 v1

基础 URL：`https://home.sunny-string.cn/longbridge`。所有 `/v1/*` 请求携带 `Authorization: Bearer $LONGBRIDGE_ROUTER_TOKEN`。

## 状态与发现

`GET /v1/status` → `{"code":0,"data":{"paused":false,"oauth":{"authorized":false,"needs_authorization":true},"markets":["CN","HK","US"],"scopes":["quote:read"]}}`。OAuth 还包含到期时间与最近刷新时间，均为 Unix 秒；不返回上游凭证。

`GET /v1/catalog` → `data.operations[]` 列出 `{method,path,scope}`，`data.markets[]` 列出该 Token 的市场范围。

## 混合报价

`GET /v1/quotes?symbols=600519.SH,700.HK,AAPL.US`，最多 500 个代码，逗号分隔，统一大写。返回：

```json
{
  "code": 0,
  "data": {"securities": [{"symbol": "700.HK", "last_done": "原始上游价格字符串"}]},
  "meta": {"routes": {"CN": "direct", "HK": "proxy", "US": "proxy"}, "missing_symbols": [], "request_id": "..."}
}
```

上例只展示结构，价格是说明文本；真实字段与内容来自长桥。响应对象可包含盘前、盘后、隔夜等数据，具体权限和可用性以账户为准。`meta.missing_symbols` 列出上游缺失的代码。任一市场请求失败整体返回错误，不交付部分结果。

## 指定市场的读取

`POST /v1/markets/{market}/request`，market 取 `CN/HK/US`。内容：

```json
{"method":"POST","path":"/quote/quotes","params":{},"body":{"symbol":["700.HK"]}}
```

成功：`{"code":0,"data":<上游data>,"meta":{"market":"HK","route":"proxy","request_id":"..."}}`。method 是上游 HTTP 方法。params 是上游查询参数；body 是上游 JSON。禁止完整 URL、查询字符串混入 path、非清单路径和交易写入。同一次显式市场请求中的所有 symbol/market 必须一致。

### 行情 HTTP 操作（上游 POST）

| path | 典型 body | 说明 |
| --- | --- | --- |
| `/quote/quotes` | `{"symbol":["700.HK"]}` | 批量报价 |
| `/quote/static-info` | `{"symbol":["700.HK"]}` | 基础信息 |
| `/quote/depth` | `{"symbol":"700.HK"}` | 买卖档位 |
| `/quote/brokers` | `{"symbol":"700.HK"}` | 经纪商队列 |
| `/quote/trades` | `{"symbol":"700.HK","count":20}` | 最近成交 |
| `/quote/intraday` | `{"symbol":"700.HK"}` | 分时 |
| `/quote/candlesticks` | `{"symbol":"700.HK","period":1000,"count":100,"adjust_type":0}` | 日 K；period/adjust_type 使用 proto 数值枚举 |
| `/quote/capital-flow` | `{"symbol":"700.HK"}` | 资金流 |
| `/quote/capital-distribution` | `{"symbol":"700.HK"}` | 资金分布 |
| `/quote/markets/trading-days` | 见对应长桥 proto 请求 | 交易日 |

其他上游 POST 包括 options/quotes、warrants/quotes、participants、options/expiry-dates、warrants/issuers、warrants、calc-indexes、history-candlesticks、markets/trading-sessions。准确支持列表以 `/v1/catalog` 为准。

路径依据官方 SDK 的 [cmd_code.rs](https://github.com/longbridge/openapi/blob/main/rust/src/quote/cmd_code.rs) 映射。请求体依据 [quote proto](https://github.com/longbridge/openapi/blob/main/rust/crates/proto/src/longbridge.quote.v1.rs)，不直接照搬 SDK 的 camelCase 参数。上游 proto JSON 可能省略默认字段并把 64 位数编码成字符串。

### 行情 REST 操作（上游 GET）

例如市场温度：

```json
{"method":"GET","path":"/v1/quote/market_temperature","params":{"market":"CN"}}
```

在 `/v1/markets/CN/request` 调用。另有 history_market_temperature、get_security_list、filings、market-status、watchlist 和期权统计等，详见 catalog。读取权限不意味着长桥账户一定已开通对应上游产品。

### 账户读取

需要 `account:read`：`GET /v1/asset/account`、`/v1/asset/cashflow`、`/v1/asset/stock`、`/v1/asset/fund`、`/v1/trade/order/today`、`/v1/trade/order/history`、`/v1/trade/order`、`/v1/trade/execution/today`、`/v1/trade/execution/history`。通过 `/v1/markets/US/request` 等外层 POST 发送。上游跨市场账户汇总不按市场裁剪；market 限制选择的出站通道，`account:read` 授予完整账户只读权限。

## 失败契约

HTTP 非 2xx：`{"error":{"code":"oauth_authorization_required"},"request_id":"..."}`。部分上游错误带 `error.status` 或上游数值 `error.upstream_code`。错误正文不会透出上游 access/refresh token。消费者应以 HTTP 状态作第一层判断，不依赖错误文案。每个响应包含 `X-Request-ID`。

401 更新应用凭证；403 检查范围和账户权限；409 让管理员打开管理网页处理；422 修正请求；429 遵循 Retry-After；503 等管理员恢复；502/504 有限退避重试。成功也应检查缺失证券和数据时间。

Token 的每分钟额度按外层请求计算，混合查询消耗一笔；上游调用最多 4 并发、全服务默认 8 次/秒。行情响应未添加缓存，不保证请求返回的数据属于当前交易时段。
