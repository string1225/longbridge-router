"""Standard-library consumer for 139 Longbridge Router. No OAuth or admin access."""

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class RouterError(Exception):
    def __init__(self, status, code, request_id=""):
        self.status, self.code, self.request_id = status, code, request_id
        super().__init__(f"Router HTTP {status}: {code} (request_id={request_id})")


class RouterClient:
    def __init__(self, base_url, token, timeout=65):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Use an HTTPS gateway URL")
        if parsed.username or parsed.query or parsed.fragment or not parsed.hostname:
            raise ValueError("Invalid gateway URL")
        if not token:
            raise ValueError("Application token required")
        self.base_url, self.token, self.timeout = base_url.rstrip("/"), token, timeout

        # Never follow redirects with the Authorization header attached.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        self.opener = urllib.request.build_opener(NoRedirect())

    @classmethod
    def from_env(cls):
        return cls(
            os.environ.get("LONGBRIDGE_ROUTER_URL", "https://home.sunny-string.cn/longbridge"),
            os.environ.get("LONGBRIDGE_ROUTER_TOKEN", ""),
        )

    def call(self, path, payload=None):
        if not path.startswith("/v1/") or path.startswith("//"):
            raise ValueError("Consumer v1 path required")
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
        )
        for attempt in range(3):
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                try:
                    body = json.loads(exc.read(262144))
                except (ValueError, UnicodeError):
                    body = {}
                if exc.code in {429, 502, 504} and attempt < 2:
                    try:
                        delay = float(exc.headers.get("Retry-After", 2**attempt))
                    except ValueError:
                        delay = 2**attempt
                    if delay < 0 or delay > 60:
                        raise RouterError(
                            exc.code,
                            "retry_after_out_of_budget",
                            exc.headers.get("X-Request-ID", ""),
                        ) from None
                    time.sleep(delay + random.random() * 0.3)
                    continue
                error = body.get("error", {})
                code = error.get("code", "http_error") if isinstance(error, dict) else "http_error"
                raise RouterError(exc.code, code, exc.headers.get("X-Request-ID", "")) from None
            except urllib.error.URLError:
                raise RouterError(0, "gateway_unreachable") from None

    def status(self):
        return self.call("/v1/status")

    def catalog(self):
        return self.call("/v1/catalog")

    def quotes(self, symbols):
        return self.call("/v1/quotes?" + urllib.parse.urlencode({"symbols": ",".join(symbols)}))

    def request(self, market, method, path, body=None, params=None):
        if market not in {"CN", "HK", "US"}:
            raise ValueError("Market must be CN, HK or US")
        return self.call(
            "/v1/markets/" + market + "/request",
            {
                "method": method,
                "path": path,
                "body": body or {},
                "params": params or {},
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("catalog")
    quotes = commands.add_parser("quotes")
    quotes.add_argument("symbols", nargs="+")
    request = commands.add_parser("request")
    request.add_argument("market", choices=["CN", "HK", "US"])
    request.add_argument("method", choices=["GET", "POST"])
    request.add_argument("path")
    request.add_argument("--body", default="{}")
    request.add_argument("--params", default="{}")
    args = parser.parse_args()
    try:
        client = RouterClient.from_env()
        if args.command == "quotes":
            result = client.quotes(args.symbols)
        elif args.command == "request":
            result = client.request(
                args.market, args.method, args.path, json.loads(args.body), json.loads(args.params)
            )
        else:
            result = getattr(client, args.command)()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RouterError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
