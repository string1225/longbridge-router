import json
from datetime import UTC, datetime

import httpx
import pytest

from research.collect import Collector, completed_end_date, date_windows, load_client_config


def test_unadjusted_history_has_separate_cache_identity_and_upstream_adjust_type(tmp_path):
    seen = []

    def provider(req):
        body = json.loads(req.content)["body"]
        seen.append(body["adjust_type"])
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "candlesticks": [{"timestamp": "1700000000", "open": "10", "close": "10"}]
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        for adjust in (0, 1, 0, 1):
            collector = Collector(
                client, "https://example.com", tmp_path, pause=0, adjust_type=adjust
            )
            assert collector.history("BABA.US", "20231101", "20231130") is not None
    assert seen == [0, 1]
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_completed_dates_respect_market_close():
    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)  # 20:00 Shanghai,07:00 New York
    assert completed_end_date("CN", now) == "20261102"
    assert completed_end_date("HK", now) == "20261102"
    assert completed_end_date("US", now) == "20261101"


def test_windows_are_nonoverlapping_and_under_thousand_weekdays():
    windows = date_windows("20211101", "20261030")
    assert windows[0][0] == "20211101" and windows[-1][1] == "20261030"
    assert len(windows) == 2
    assert windows[0][1] < windows[1][0]


def test_private_client_config_rejects_expiry_without_echoing_secret(tmp_path):
    p = tmp_path / "client.json"
    p.write_text(
        json.dumps({"base_url": "https://example.com", "token": "secret-value", "expires_at": 1})
    )
    with pytest.raises(ValueError, match="expired") as exc:
        load_client_config(p)
    assert "secret-value" not in str(exc.value)


def test_collection_cache_and_market_routes(tmp_path):
    seen = []

    def provider(req):
        data = json.loads(req.content)
        seen.append(data)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "symbol": data["body"]["symbol"],
                    "candlesticks": [{"timestamp": "1700000000", "open": "10", "close": "11"}],
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        collector = Collector(client, "https://example.com/longbridge", tmp_path, pause=0)
        one = collector.history("941.HK", "20231101", "20261030")
        two = collector.history("941.HK", "20231101", "20261030")
    assert len(seen) == 1
    assert one == two
    assert seen[0]["path"] == "/quote/history-candlesticks"
    assert seen[0]["body"]["adjust_type"] == 1


def test_failed_collection_does_not_become_valid_cache(tmp_path):
    count = 0

    def provider(req):
        nonlocal count
        count += 1
        return httpx.Response(409, json={"error": {"code": "oauth_authorization_required"}})

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        collector = Collector(client, "https://example.com", tmp_path, pause=0)
        assert collector.history("BABA.US", "20231101", "20261030") is None
        assert collector.history("BABA.US", "20231101", "20261030") is None
    assert count == 2
    assert not list(tmp_path.glob("*.json"))


def test_incremental_forward_adjustment_refreshes_rebased_history(tmp_path):
    calls = []
    old = [
        {"timestamp": "1672704000", "open": "20", "close": "20"},
        {"timestamp": "1700000000", "open": "10", "close": "10"},
    ]
    rebased = [
        {"timestamp": "1672704000", "open": "10", "close": "10"},
        {"timestamp": "1700000000", "open": "5", "close": "5"},
        {"timestamp": "1701417600", "open": "6", "close": "6"},
    ]

    def provider(req):
        body = json.loads(req.content)["body"]
        calls.append(body)
        rows = old if len(calls) == 1 else (rebased[1:] if len(calls) == 2 else rebased)
        return httpx.Response(200, json={"code": 0, "data": {"candlesticks": rows}})

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        collector = Collector(client, "https://example.com", tmp_path, pause=0)
        collector.history("941.HK", "20230101", "20231130")
        result = collector.history("941.HK", "20230101", "20231201")
    assert calls[1]["date_request"]["start_date"] <= "20231114"
    assert len(calls) == 3
    assert result["data"]["candlesticks"][0]["close"] == "10"


def test_cached_history_never_returns_future_requested_dates(tmp_path):
    rows = [
        {"timestamp": "1700000000", "open": "10", "close": "10"},
        {"timestamp": "1701417600", "open": "11", "close": "11"},
    ]
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"code": 0, "data": {"candlesticks": rows}})
    )
    with httpx.Client(transport=transport) as client:
        collector = Collector(client, "https://example.com", tmp_path, pause=0)
        collector.history("941.HK", "20231101", "20231202")
        shorter = collector.history("941.HK", "20231101", "20231130")
    assert len(shorter["data"]["candlesticks"]) == 1


def test_partial_rebase_reload_preserves_previous_cache(tmp_path):
    calls = 0
    rows = [
        {"timestamp": "1672704000", "open": "20", "close": "20"},
        {"timestamp": "1700000000", "open": "10", "close": "10"},
    ]

    def provider(req):
        nonlocal calls
        calls += 1
        sample = rows if calls == 1 else [{"timestamp": "1700000000", "open": "5", "close": "5"}]
        return httpx.Response(200, json={"code": 0, "data": {"candlesticks": sample}})

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        collector = Collector(client, "https://example.com", tmp_path, pause=0)
        collector.history("941.HK", "20230101", "20231130")
        old_cache = next(tmp_path.glob("*.json")).read_bytes()
        result = collector.history("941.HK", "20230101", "20231201")
        assert result is None
        assert collector.errors[-1]["error"] == "incomplete_history_refresh"
        assert next(tmp_path.glob("*.json")).read_bytes() == old_cache
