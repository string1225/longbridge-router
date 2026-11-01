---
name: longbridge-router
description: 为其他项目接入 139 服务器上的长桥 OAuth 行情中转服务，开发 A 股、港股、美股查询与账户只读应用。用于该中转的接口调用、鉴权、错误排查和应用后端集成；不用于直接管理长桥 OAuth 或执行交易。
---

# 139 长桥接口开发

服务地址：`https://home.sunny-string.cn/longbridge`。管理页面位于同地址末尾加 `/`。服务端代理维护长桥 OAuth；消费应用只需独立的应用 Token。

## 接入

从项目现有密钥配置中查找 `LONGBRIDGE_ROUTER_URL` 和 `LONGBRIDGE_ROUTER_TOKEN`；没有 Token 时让项目所有者在管理页的「应用 Token」中新建。不要读取管理员密码、139 的加密密钥或长桥 refresh token，不要用管理 Cookie 代替应用凭证。

1. 在目标应用后端发送 `Authorization: Bearer <应用 Token>`，先 `GET /v1/status` 验证凭证和可用市场。
2. 使用 `GET /v1/catalog` 发现当前凭证支持的读取操作。需要确切 JSON 契约时读取 `<服务地址>/openapi.json`，并阅读 [references/api.md](references/api.md)。
3. 查询常用报价：`GET /v1/quotes?symbols=600519.SH,700.HK,AAPL.US`。市场由代码后缀推导，自动拆分 CN/HK/US，结果按请求顺序排列。
4. 深度、K 线等通过 `POST /v1/markets/{CN|HK|US}/request`，请求体中的 `method` 和 `path` 表示上游的操作。例如 `{"method":"POST","path":"/quote/depth","body":{"symbol":"700.HK"}}`。

市场路由：A 股 `.SH/.SZ/.BJ` → `CN` → 国内直连；`.HK` → `HK`、`.US` → `US` → 139 VPN。不要在消费项目额外配置 VPN，也不要通过更改 market 绕过授权或分流。显式市场请求不接受其他市场的 symbol。

## 数据与错误

- Token 放在后端环境变量或密钥管理器；浏览器通过自己应用的后端调用。不要把它放在 URL、前端构建变量、日志或仓库。无需设置管理员密码。
- `quote:read` 允许行情读取；`account:read` 允许列出的资金、持仓和订单只读接口。交易写入未开放，不存在通用任意 URL 代理。
- 报价、成交量和金额保持上游 JSON 类型与字符串精度，不要先转浮点再转回。部分低层行情字段使用 proto JSON 的命名、枚举和时间戳；参考长桥对应接口，而不是假设 SDK 对象结构。
- 行情权限和是否实时取决于长桥账户套餐；HTTP 200、OAuth 已连接和「网络检查通过」均不能证明某市场具备实时行情权限。解析返回时间戳，不在休市时宣称实时更新。
- 401：应用 Token 无效、到期或已撤销；403：范围或市场权限不足，或上游行情权限拒绝；409：管理员需要在网页完成/恢复长桥授权；422：参数错误；429：遵循 `Retry-After`；503：服务暂停；502/504：上游错误/超时。
- 对幂等读取的 429/502/504 最多重试两次，使用退避和抖动；409 不循环重试。保留响应头 `X-Request-ID` 供排查。
- 混合查询有任一市场失败会整体报错。成功返回的 `meta.missing_symbols` 必须检查，不能把缺失证券当成零价格。

## 可运行客户端

`scripts/client.py` 仅使用 Python 标准库，读取上述两个环境变量。可以直接运行：

```text
python scripts/client.py status
python scripts/client.py catalog
python scripts/client.py quotes 600519.SH 700.HK AAPL.US
python scripts/client.py request HK POST /quote/depth --body '{"symbol":"700.HK"}'
```

也可导入 `RouterClient`：`RouterClient.from_env().quotes(["700.HK"])`。客户端不记录密钥，错误对象包含 HTTP 状态、错误代码和 request ID。

开发完成后验证真实读取（先 status，再在授权范围内取一个标的），保留 request ID 和字段契约；凭证或 OAuth 尚未准备好时，明确区分模拟测试与已完成的真实验收。
