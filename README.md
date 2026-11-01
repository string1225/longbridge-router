# Longbridge Router

139 服务器上的长桥 OAuth 和市场数据中转，提供中文管理台、独立应用 Token 和开发 Agent Skill。

管理台：**https://home.sunny-string.cn/longbridge/**

API 基础地址：`https://home.sunny-string.cn/longbridge`

## 使用

1. 使用私有交接文件中的初始密码登录，可在管理设置中修改密码。
2. 点击「连接长桥账户」，在长桥页面登录并同意授权。服务加密保存凭证，自动维护 refresh token。
3. 在「应用 Token」为每个项目创建独立凭证，选择市场、权限、额度和有效期。完整 Token 仅显示一次，可轮换或撤销。
4. 在目标应用的服务端配置：

```text
LONGBRIDGE_ROUTER_URL=https://home.sunny-string.cn/longbridge
LONGBRIDGE_ROUTER_TOKEN=<管理台签发的应用 Token>
```

```sh
curl --get "$LONGBRIDGE_ROUTER_URL/v1/quotes" \
  --data-urlencode 'symbols=600519.SH,700.HK,AAPL.US' \
  -H "Authorization: Bearer $LONGBRIDGE_ROUTER_TOKEN"
```

消费端不管理长桥 OAuth。Token 只保存在应用后端。默认只允许行情读取；可单独授予完整账户只读权限。订单提交、撤改单等交易写入未开放。

## 路由和数据

| 市场 | 证券后缀 | 上游 | 网络 |
| --- | --- | --- | --- |
| A 股 CN | `.SH/.SZ/.BJ` | `openapi.longbridge.cn` | 不设置 HTTP 代理，Mihomo 显式 DIRECT |
| 港股 HK | `.HK` | `openapi.longbridge.com` | `127.0.0.1:7890` + 显式 PROXY |
| 美股 US | `.US` | `openapi.longbridge.com` | `127.0.0.1:7890` + 显式 PROXY |

混合报价按市场拆分，保留价格字符串精度和请求顺序。任一市场失败则整体报错；成功仍应检查 `meta.missing_symbols`。账户汇总不按市场裁剪，`account:read` 授予完整账户只读权限。

网络可达、OAuth 已连接不代表已有实时行情权限。美国账户可能受长桥国内域名限制；服务遵循固定市场路由，不会失败后切换出站方式。时效性依据响应时间戳、交易时段及账户权限判断。

## 接口和 Skill

- `GET /healthz`：进程和数据库健康。
- `GET /v1/status`：应用权限、OAuth 摘要和暂停状态。
- `GET /v1/catalog`：当前 Token 可用的只读操作。
- `GET /v1/quotes?symbols=...`：混合市场报价。
- `POST /v1/markets/{CN|HK|US}/request`：显式市场和精确白名单操作。
- `GET /openapi.json`：机器可读契约。

完整消费文档见 [skills/longbridge-router/references/api.md](skills/longbridge-router/references/api.md)。将整个 `skills/longbridge-router` 文件夹复制到其他机器的 `~/.codex/skills/`，或在管理台「开发接入」下载 ZIP。内含无依赖 Python 客户端：

```sh
python skills/longbridge-router/scripts/client.py status
python skills/longbridge-router/scripts/client.py quotes 600519.SH 700.HK AAPL.US
```

401 更新 Token，403 检查权限，409 在管理台恢复长桥授权，422 修正参数，429 遵循 Retry-After，503 服务暂停，502/504 有限退避重试。响应含 `X-Request-ID`；上游凭证不进入响应或调用日志。

## 开发与测试

两类股票策略研究、独立候选池、只读采集与每日报告见 [research/README.md](research/README.md)。原始行情和研究凭证保存在仓库外。

Python 3.11+，创建 venv 后：

```sh
python -m pip install -r requirements.lock
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check router tests deploy skills
```

配置 `ROUTER_PUBLIC_URL`、`ROUTER_ENCRYPTION_KEY`（Fernet key）、`ROUTER_ADMIN_PASSWORD_HASH`（`router.security.hash_password` 生成），以及可选 `ROUTER_DATA_DIR/ROUTER_PROXY_URL/ROUTER_UPSTREAM_RPS`。本地可使用 `http://127.0.0.1:18090`，生产必须 HTTPS。

启动：`uvicorn router.main:app --host 127.0.0.1 --port 18090`。子路径需在 Uvicorn 配置 `--root-path`。单 worker：刷新锁和限流在进程内，不能直接增加 worker 数量。

OAuth scope 默认留空，与官方 SDK 一致；若配置 `ROUTER_OAUTH_SCOPE`，会与实时 Discovery 校验，不能照搬旧示例值 `3`。

## 139 运维

```sh
systemctl status longbridge-router
journalctl -u longbridge-router -n 50 --no-pager
curl -fsS https://home.sunny-string.cn/longbridge/healthz
sudo /opt/longbridge-router/current/.venv/bin/python /opt/longbridge-router/current/deploy/verify-routing.py
```

代码：`/opt/longbridge-router/releases/` 和 `current`；状态：`/var/lib/longbridge-router/router.sqlite3`；配置：`/etc/longbridge-router.env`（root 0600）。初始密码文件：`/home/junte/.config/longbridge-router/bootstrap.txt`；改密后旧文件不再更新。

备份须同时保存 SQLite 和原加密密钥。使用 SQLite 在线备份 API，或停服后复制数据库及 WAL，不能只复制运行中的主数据库。密钥丢失将无法恢复授权。更新保留配置和数据，不上传这些文件到仓库。

发布：`python deploy/package.py artifacts/release.tar.gz`，上传后解压至新的 `/opt/longbridge-router/releases/<version>`，以 root 执行其中 `deploy/install.sh`。脚本校验并热加载两个域名路由，安装独立服务并检查健康，验证 Nginx 后 reload。回滚时将 `current` 指回此前版本并重启此服务。

Nginx 只记录无 query 的 `$uri`，Uvicorn access log 关闭。Cookie 使用 Secure/HttpOnly/SameSite；管理写操作校验 CSRF 与 Origin；应用凭证只存哈希，OAuth 凭证加密存储。

## 验证边界

自动化覆盖认证、CSRF、Token 生命周期、分流、PKCE、state 重放、refresh token 轮换与并发、空 proto 响应及数据中心头。公网 Playwright 覆盖桌面/手机、登录、网络检查、Token 创建/轮换/撤销、暂停/恢复、记录和 Skill 下载。

真实行情需所有者完成长桥网页登录授权后再验收。未授权的 401 只证明接口和网络可达。

官方参考：[OAuth](https://open.longbridge.com/zh-CN/docs/api)、[HTTP 行情映射](https://github.com/longbridge/openapi/blob/main/rust/src/quote/cmd_code.rs)、[OAuth 请求头](https://github.com/longbridge/openapi/blob/main/rust/crates/httpclient/src/request.rs)。
