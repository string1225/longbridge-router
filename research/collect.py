"""Read-only, cached Longbridge research collection; never logs credentials."""

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from datetime import time as clock_time
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx


def market_of(symbol):
    suffix = symbol.rsplit(".", 1)[-1]
    return "CN" if suffix in {"SH", "SZ", "BJ"} else suffix


def completed_end_date(market, now=None):
    """Completed-session date bound; exchange holidays are resolved by returned bars."""
    now = now or datetime.now(UTC)
    local = now.astimezone(ZoneInfo("America/New_York" if market == "US" else "Asia/Shanghai"))
    cutoff = clock_time(16, 30) if market == "US" else clock_time(17)
    date = local.date() if local.time() >= cutoff else local.date() - timedelta(days=1)
    return date.strftime("%Y%m%d")


def date_windows(start, end):
    begin = datetime.strptime(start.replace("-", ""), "%Y%m%d").date()
    final = datetime.strptime(end.replace("-", ""), "%Y%m%d").date()
    result = []
    # 1095 calendar days contain fewer than1000 weekdays, avoiding provider truncation.
    while begin <= final:
        stop = min(begin + timedelta(days=1094), final)
        result.append((begin.strftime("%Y%m%d"), stop.strftime("%Y%m%d")))
        begin = stop + timedelta(days=1)
    return result


def load_client_config(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    parsed = urlsplit(value.get("base_url", ""))
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Research gateway must be a fixed HTTPS URL")
    if not value.get("token"):
        raise ValueError("Research application credential missing")
    if float(value.get("expires_at", 0)) <= time.time():
        raise ValueError(
            "Research application credential expired; owner must renew in management UI"
        )
    return value


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class Collector:
    def __init__(self, client, base_url, cache_dir, pause=0.6):
        self.client, self.base_url, self.pause = client, base_url.rstrip("/"), pause
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.errors, self.requests, self.cache_hits = [], 0, 0

    @staticmethod
    def filter_response(response, symbol, start, end):
        zone = ZoneInfo("America/New_York" if market_of(symbol) == "US" else "Asia/Shanghai")
        rows = [
            row
            for row in response["data"].get("candlesticks", [])
            if start
            <= datetime.fromtimestamp(int(row["timestamp"]), zone).strftime("%Y%m%d")
            <= end
        ]
        return {"code": 0, "data": {"symbol": symbol, "candlesticks": rows}}

    def fetch_history(self, symbol, start, end):
        combined = {}
        for begin_date, end_date in date_windows(start, end):
            response = self.request(
                market_of(symbol),
                "/quote/history-candlesticks",
                {
                    "symbol": symbol,
                    "period": 1000,
                    "adjust_type": 1,
                    "query_type": 2,
                    "date_request": {"start_date": begin_date, "end_date": end_date},
                },
            )
            if response is None:
                return None
            rows = response.get("data", {}).get("candlesticks") or []
            if not isinstance(rows, list):
                self.errors.append({"symbol": symbol, "error": "unexpected_history_schema"})
                return None
            combined.update({int(row["timestamp"]): row for row in rows})
        return combined

    def request(self, market, endpoint, body):
        for attempt in range(3):
            if self.pause:
                time.sleep(self.pause)
            self.requests += 1
            try:
                response = self.client.post(
                    self.base_url + "/v1/markets/" + market + "/request",
                    json={"method": "POST", "path": endpoint, "body": body},
                )
            except httpx.RequestError:
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
                self.errors.append(
                    {"market": market, "endpoint": endpoint, "error": "network_error"}
                )
                return None
            if response.status_code in {429, 502, 504} and attempt < 2:
                try:
                    delay = float(response.headers.get("Retry-After", 2**attempt))
                except ValueError:
                    delay = 2**attempt
                if 0 <= delay <= 30:
                    time.sleep(delay)
                    continue
            if not response.is_success:
                self.errors.append(
                    {
                        "market": market,
                        "endpoint": endpoint,
                        "http": response.status_code,
                        "request_id": response.headers.get("X-Request-ID"),
                    }
                )
                return None
            return response.json()
        return None

    def history(self, symbol, start, end):
        start, end = start.replace("-", ""), end.replace("-", "")
        identity = hashlib.sha256((symbol + "-forward-day").encode()).hexdigest()[:20]
        path = self.cache_dir / (identity + ".json")
        cached = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        existing = []
        if cached and cached["start"] <= start:
            existing = cached["response"]["data"].get("candlesticks", [])
            if cached["end"] >= end:
                self.cache_hits += 1
                return self.filter_response(cached["response"], symbol, start, end)
            begin = max(
                start,
                (datetime.strptime(cached["end"], "%Y%m%d") - timedelta(days=60)).strftime(
                    "%Y%m%d"
                ),
            )
        else:
            begin = start
        combined = {int(row["timestamp"]): row for row in existing}
        fresh = self.fetch_history(symbol, begin, end)
        if fresh is None:
            return None
        if existing:
            overlap = set(combined) & set(fresh)
            rebase = not overlap or any(
                str(combined[ts].get(k)) != str(fresh[ts].get(k))
                for ts in overlap
                for k in ("open", "close", "high", "low")
            )
            if rebase:
                # Do not stitch two different adjustment bases. Reload safely instead.
                fresh = self.fetch_history(symbol, start, end)
                if fresh is None:
                    return None
                previous_in_range = self.filter_response(cached["response"], symbol, start, end)[
                    "data"
                ]["candlesticks"]
                if not {int(row["timestamp"]) for row in previous_in_range} <= set(fresh):
                    self.errors.append({"symbol": symbol, "error": "incomplete_history_refresh"})
                    return None
                combined = {}
        combined.update(fresh)
        response = {
            "code": 0,
            "data": {"symbol": symbol, "candlesticks": [combined[k] for k in sorted(combined)]},
        }
        response = self.filter_response(response, symbol, start, end)
        if not response["data"]["candlesticks"] and existing:
            # An empty provider result must not silently replace previously valid history.
            self.errors.append({"symbol": symbol, "error": "empty_history_after_refresh"})
            return None
        save_json(path, {"start": start, "end": end, "response": response})
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--universe", type=Path, default=Path(__file__).with_name("universe.json"))
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--start", default="20211101")
    parser.add_argument("--end")
    parser.add_argument("--max-symbols", type=int, default=40)
    args = parser.parse_args()
    config = load_client_config(args.config)
    universe = json.loads(args.universe.read_text(encoding="utf-8"))
    symbols = list(
        dict.fromkeys(
            item["symbol"]
            for role in ("dividend_candidates", "volatility_candidates", "benchmarks")
            for item in universe[role]
        )
    )
    if len(symbols) > args.max_symbols or args.max_symbols > 60:
        raise SystemExit("Candidate symbol quota budget exceeded")
    now = datetime.now(UTC)
    end_by_market = {
        m: min(completed_end_date(m, now), args.end.replace("-", ""))
        if args.end
        else completed_end_date(m, now)
        for m in ("CN", "HK", "US")
    }
    result = {
        "version": 1,
        "retrieved_at": now.isoformat(),
        "source": "139 Longbridge Router",
        "requested_start": args.start,
        "requested_end_by_market": end_by_market,
        "credential_expires_at": config["expires_at"],
        "history": {},
        "indexes": {},
        "static": {},
        "quotes": {},
        "errors": [],
    }
    with httpx.Client(
        trust_env=False,
        follow_redirects=False,
        timeout=65,
        headers={"Authorization": "Bearer " + config["token"]},
    ) as client:
        status = client.get(config["base_url"].rstrip("/") + "/v1/status")
        if not status.is_success:
            raise SystemExit(
                "Research application authentication failed: HTTP " + str(status.status_code)
            )
        state = status.json()["data"]
        if state["paused"] or not state["oauth"]["authorized"]:
            raise SystemExit("Research gateway is paused or requires owner OAuth authorization")
        collector = Collector(client, config["base_url"], args.cache)
        for market in ("CN", "HK", "US"):
            group = [s for s in symbols if market_of(s) == market]
            result["indexes"][market] = collector.request(
                market,
                "/quote/calc-indexes",
                {"symbols": group, "calc_index": [1, 6, 10, 12, 13, 14]},
            )
            result["static"][market] = collector.request(
                market, "/quote/static-info", {"symbol": group}
            )
        for i, symbol in enumerate(symbols, 1):
            response = collector.history(symbol, args.start, end_by_market[market_of(symbol)])
            result["history"][symbol] = response
            count = len((response or {}).get("data", {}).get("candlesticks", []))
            print(
                json.dumps(
                    {"progress": i, "total": len(symbols), "symbol": symbol, "bars": count},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if collector.errors and collector.errors[-1].get("http") in {401, 403, 409}:
                break
        result["errors"] = collector.errors
        result["collection"] = {"requests": collector.requests, "cache_hits": collector.cache_hits}
    save_json(args.output, result)
    print(
        json.dumps(
            {"saved": str(args.output), "errors": len(result["errors"]), **result["collection"]},
            ensure_ascii=False,
        )
    )
    return 0 if not result["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
