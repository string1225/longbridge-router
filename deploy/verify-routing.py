"""Run as root on 139 to verify live TUN routing without broker credentials."""

import asyncio
import json
import re
import ssl
from pathlib import Path

import httpx


async def main():
    source = Path("/etc/mihomo/config.yaml").read_text()
    match = re.search(r"^secret:\s*(.+)$", source, re.M)
    secret = match.group(1).strip().strip("\"'") if match else ""
    async with (
        httpx.AsyncClient(trust_env=False, timeout=20) as direct,
        httpx.AsyncClient(trust_env=False, proxy="http://127.0.0.1:7890", timeout=20) as proxy,
    ):
        cn, overseas = await asyncio.gather(
            direct.get("https://openapi.longbridge.cn/.well-known/oauth-authorization-server"),
            proxy.get("https://openapi.longbridge.com/.well-known/oauth-authorization-server"),
        )
        assert cn.status_code == overseas.status_code == 200
        # Keep two verified TLS connections open while sampling the controller.
        # HTTP keepalive can end before a snapshot and would make checks intermittent.
        tls = ssl.create_default_context()
        _, cn_socket = await asyncio.wait_for(
            asyncio.open_connection("openapi.longbridge.cn", 443, ssl=tls), timeout=20
        )
        proxy_reader, global_socket = await asyncio.open_connection("127.0.0.1", 7890)
        try:
            global_socket.write(
                b"CONNECT openapi.longbridge.com:443 HTTP/1.1\r\n"
                b"Host: openapi.longbridge.com:443\r\n\r\n"
            )
            await global_socket.drain()
            handshake = await asyncio.wait_for(proxy_reader.readuntil(b"\r\n\r\n"), timeout=20)
            assert handshake.split()[1] == b"200"
            await global_socket.start_tls(tls, server_hostname="openapi.longbridge.com")
            controller = await direct.get(
                "http://127.0.0.1:9090/connections", headers={"Authorization": "Bearer " + secret}
            )
        finally:
            cn_socket.close()
            global_socket.close()
        observed = []
        for connection in controller.json().get("connections", []):
            host = connection.get("metadata", {}).get("host", "")
            if host in {"openapi.longbridge.cn", "openapi.longbridge.com"}:
                observed.append(
                    {
                        "host": host,
                        "rule": connection.get("rule"),
                        "payload": connection.get("rulePayload"),
                        "route": "direct" if "DIRECT" in connection.get("chains", []) else "proxy",
                    }
                )
        assert any(x["host"].endswith(".cn") and x["route"] == "direct" for x in observed)
        assert any(x["host"].endswith(".com") and x["route"] == "proxy" for x in observed)
        cn_quote, global_quote = await asyncio.gather(
            direct.post(
                "https://openapi.longbridge.cn/quote/quotes", json={"symbol": ["600519.SH"]}
            ),
            proxy.post("https://openapi.longbridge.com/quote/quotes", json={"symbol": ["700.HK"]}),
        )
        assert cn_quote.status_code == global_quote.status_code == 401
        print(
            json.dumps(
                {
                    "discovery": {"CN": cn.status_code, "global": overseas.status_code},
                    "quote_endpoint_without_auth": {
                        "CN": cn_quote.status_code,
                        "global": global_quote.status_code,
                    },
                    "observed_routes": observed,
                    "account_data": "requires owner OAuth consent",
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
