import asyncio
import re
import time

import httpx
from fastapi import HTTPException

MARKETS = {"CN", "HK", "US"}
BASES = {"CN": "https://openapi.longbridge.cn", "global": "https://openapi.longbridge.com"}

# Exact read operations from the official SDK's rust/src/quote/cmd_code.rs.
QUOTE_PATHS = {
    "/quote/markets/trading-sessions",
    "/quote/markets/trading-days",
    "/quote/static-info",
    "/quote/quotes",
    "/quote/options/quotes",
    "/quote/warrants/quotes",
    "/quote/depth",
    "/quote/brokers",
    "/quote/participants",
    "/quote/trades",
    "/quote/intraday",
    "/quote/candlesticks",
    "/quote/options/expiry-dates",
    "/quote/warrants/issuers",
    "/quote/warrants",
    "/quote/capital-flow",
    "/quote/capital-distribution",
    "/quote/calc-indexes",
    "/quote/history-candlesticks",
}
GET_PATHS = {
    "/v1/quote/get_security_list",
    "/v1/quote/market_temperature",
    "/v1/quote/history_market_temperature",
    "/v1/quote/filings",
    "/v1/quote/short-positions/hk",
    "/v1/quote/short-positions/us",
    "/v1/quote/short-trades/hk",
    "/v1/quote/short-trades/us",
    "/v1/quote/option-volume-stats",
    "/v1/quote/option-volume-stats/daily",
    "/v1/watchlist/groups",
    "/v1/quote/market-status",
}
ACCOUNT_PATHS = {
    "/v1/asset/account",
    "/v1/asset/cashflow",
    "/v1/asset/stock",
    "/v1/asset/fund",
    "/v1/trade/order/today",
    "/v1/trade/order/history",
    "/v1/trade/order",
    "/v1/trade/execution/today",
    "/v1/trade/execution/history",
}


def symbol_market(symbol):
    if not isinstance(symbol, str) or not re.fullmatch(
        r"[A-Z0-9._-]{1,45}\.(SH|SZ|BJ|HK|US)", symbol
    ):
        raise HTTPException(422, "invalid_symbol_use_ticker_market")
    suffix = symbol.rsplit(".", 1)[1]
    return "CN" if suffix in {"SH", "SZ", "BJ"} else suffix


def validate_market_payload(value, market):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"symbol", "symbols", "symbol_list", "symbolList"}:
                items = item if isinstance(item, list) else [item]
                for symbol in items:
                    if symbol_market(symbol) != market:
                        raise HTTPException(422, "symbol_market_mismatch")
            elif key in {"market", "markets"}:
                items = item if isinstance(item, list) else [item]
                if any(not isinstance(x, str) for x in items) or any(
                    ("CN" if x in {"SH", "SZ"} else x) != market for x in items
                ):
                    raise HTTPException(422, "market_mismatch")
            validate_market_payload(item, market)
    elif isinstance(value, list):
        for item in value:
            validate_market_payload(item, market)


def required_scope(method, path):
    if (method == "POST" and path in QUOTE_PATHS) or (method == "GET" and path in GET_PATHS):
        return "quote:read"
    if method == "GET" and path in ACCOUNT_PATHS:
        return "account:read"
    raise HTTPException(403, "endpoint_not_allowed")


class Upstream:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.clients = {
            "CN": httpx.AsyncClient(
                transport=transport, trust_env=False, timeout=20, follow_redirects=False
            ),
            "global": httpx.AsyncClient(
                transport=transport,
                proxy=None if transport else settings.proxy_url,
                trust_env=False,
                timeout=20,
                follow_redirects=False,
            ),
        }
        self.lock = asyncio.Lock()
        self.next_request = 0
        self.capacity = asyncio.Semaphore(4)

    async def close(self):
        for client in self.clients.values():
            await client.aclose()

    async def request(self, region, method, path, **kwargs):
        route = "CN" if region == "CN" else "global"
        async with self.capacity:
            async with self.lock:
                await asyncio.sleep(max(0, self.next_request - time.monotonic()))
                self.next_request = time.monotonic() + 1 / self.settings.upstream_rps
            try:
                response = await self.clients[route].request(method, BASES[route] + path, **kwargs)
            except httpx.TimeoutException as exc:
                raise HTTPException(504, "upstream_timeout") from exc
            except httpx.RequestError as exc:
                raise HTTPException(502, "upstream_connection_failed") from exc
        return response

    async def data(self, market, method, path, token, params=None, body=None, client_id=""):
        kwargs = {
            "params": params,
            "headers": {
                "Authorization": "Bearer " + token,
                "accept-language": "zh-CN",
                "x-dc-region": "us" if token.startswith("us_") else "ap",
                "X-Api-Key": client_id,
                "X-Timestamp": str(int(time.time())),
            },
        }
        if method == "POST":
            kwargs["json"] = body or {}
        response = await self.request(market, method, path, **kwargs)
        if response.status_code == 401:
            raise HTTPException(409, "upstream_authorization_required")
        if response.status_code == 403:
            raise HTTPException(403, "upstream_permission_denied")
        if response.status_code == 429:
            raise HTTPException(429, "upstream_rate_limited", headers={"Retry-After": "5"})
        if not response.is_success:
            raise HTTPException(
                502, {"error": "upstream_http_error", "status": response.status_code}
            )
        try:
            result = response.json()
        except ValueError as exc:
            raise HTTPException(502, "upstream_invalid_response") from exc
        if not isinstance(result, dict):
            raise HTTPException(502, "upstream_invalid_response")
        if str(result.get("code", 0)) != "0":
            raise HTTPException(
                502, {"error": "upstream_api_error", "upstream_code": result.get("code")}
            )
        return result

    async def connectivity(self):
        async def probe(market):
            start = time.monotonic()
            try:
                response = await self.request(
                    market, "GET", "/.well-known/oauth-authorization-server"
                )
                reachable = (
                    response.is_success
                    and response.json().get("issuer") == BASES["CN" if market == "CN" else "global"]
                )
                return {
                    "reachable": reachable,
                    "http_status": response.status_code,
                    "latency_ms": round((time.monotonic() - start) * 1000),
                    "route": "direct" if market == "CN" else "proxy",
                }
            except (HTTPException, ValueError):
                return {"reachable": False, "route": "direct" if market == "CN" else "proxy"}

        cn, overseas = await asyncio.gather(probe("CN"), probe("US"))
        return {"CN": cn, "HK": overseas, "US": overseas}
