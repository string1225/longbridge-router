import copy

import pytest

from research import fingerprint
from research.report import build_daily_report, render_text


def refresh_provenance(args):
    args[1]["provenance"] = {
        "history_fingerprint": fingerprint(args[0]["history"]),
        "universe_fingerprint": fingerprint(args[3]),
    }


def inputs():
    dataset = {
        "retrieved_at": "2026-11-01T13:00:00+00:00",
        "history": {
            "941.HK": {
                "data": {
                    "candlesticks": [
                        {
                            "timestamp": "1793289600",
                            "open": "80",
                            "close": "80",
                            "high": "81",
                            "low": "79",
                        }
                    ]
                }
            },
            "BABA.US": {
                "data": {
                    "candlesticks": [
                        {
                            "timestamp": "1793332800",
                            "open": "100",
                            "close": "100",
                            "high": "110",
                            "low": "90",
                        }
                    ]
                }
            },
        },
        "errors": [],
        "collection": {"requests": 6, "cache_hits": 2},
    }
    variants = {
        "grid_5": {
            "mean_return": -0.127,
            "mean_cagr": -0.128,
            "mean_max_drawdown": -0.298,
            "mean_trade_count": 42,
            "mean_mean_exposure": 0.60,
            "mean_excess_return_vs_half_hold": -0.012,
            "beat_half_hold_count": 0,
            "stock_count": 1,
        }
    }
    wave = {
        "aggregate": {
            "eligible_wave_count": 1,
            "eligible_symbols": ["BABA.US"],
            "periods": {"temporal_test": {"variants": variants}},
        },
        "stocks": {},
        "methodology": {"temporal_test_caveat": "already inspected"},
    }
    evidence = {
        "as_of": "2026-11-01",
        "sources": {"primary": {"url": "https://example.com"}},
        "data_status": {"complete_point_in_time_history": False},
        "candidates": [{"symbol": "941.HK", "issuer_id": "CM", "missing": ["coverage"]}],
        "events": [
            {
                "id": "event",
                "announcement_date": None,
                "ex_date": None,
                "payment_date": "2026-11-20",
            }
        ],
    }
    universe = {
        "dividend_candidates": [{"symbol": "941.HK"}],
        "volatility_candidates": [{"symbol": "BABA.US"}],
        "benchmarks": [],
    }
    args = dataset, wave, evidence, universe
    refresh_provenance(args)
    return args


def test_report_uses_exchange_dates_and_flags_incomplete_dividend_evidence():
    result = build_daily_report(*inputs(), report_date="2026-11-01")
    assert result["data"]["markets"]["HK"]["last_session"] == "2026-10-30"
    assert result["data"]["markets"]["US"]["last_session"] == "2026-10-30"
    assert result["dividend"]["backtest_status"] == "not_run"
    assert result["dividend"]["event_gaps"]["announcement_date"] == 1
    assert result["dividend"]["candidate_count"] == 1
    assert result["wave"]["eligible_count"] == 1
    assert "profit" not in result["dividend"]


def test_report_deltas_do_not_invent_new_data_when_only_retrieval_time_changes():
    args = inputs()
    previous = build_daily_report(*args, report_date="2026-11-01")
    args[0]["retrieved_at"] = "2026-11-02T12:00:00+00:00"
    current = build_daily_report(*args, report_date="2026-11-02", previous=previous)
    assert current["changes"]["history_changed_symbols"] == []
    assert current["changes"]["new_source_ids"] == []
    assert current["changes"]["wave_test_return_change"]["grid_5"] == 0


def test_history_revisions_and_new_evidence_are_visible():
    args = inputs()
    previous = build_daily_report(*args, report_date="2026-11-01")
    args[0]["history"]["BABA.US"]["data"]["candlesticks"][0]["close"] = "101"
    args[2]["sources"]["new"] = {"url": "https://example.com/new"}
    refresh_provenance(args)
    current = build_daily_report(*args, report_date="2026-11-02", previous=previous)
    assert current["changes"]["history_changed_symbols"] == ["BABA.US"]
    assert current["changes"]["new_source_ids"] == ["new"]


def test_failures_and_missing_symbols_remain_in_report():
    args = list(inputs())
    args[0] = copy.deepcopy(args[0])
    args[0]["history"]["BABA.US"] = None
    args[0]["errors"] = [{"http": 403, "market": "US"}]
    refresh_provenance(args)
    result = build_daily_report(*args, report_date="2026-11-01")
    assert result["data"]["missing_symbols"] == ["BABA.US"]
    assert result["data"]["errors"][0]["http"] == 403
    assert not result["data"]["complete"]


def test_text_labels_cross_sectional_means_and_formats_fractional_units():
    result = build_daily_report(*inputs(), report_date="2026-11-01")
    text = render_text(result)
    assert "-12.70%" in text and "29.80%" in text
    assert "60.00%" in text
    assert "不是组合收益" in text
    assert "股息策略尚未回测" in text


def test_event_revisions_do_not_disappear_behind_unchanged_source_count():
    args = inputs()
    previous = build_daily_report(*args, report_date="2026-11-01")
    args[2]["events"][0]["announcement_date"] = "2026-10-20"
    current = build_daily_report(*args, report_date="2026-11-02", previous=previous)
    assert current["changes"]["changed_event_ids"] == ["event"]


def test_stale_simulation_is_rejected_after_history_revision():
    args = inputs()
    args[0]["history"]["BABA.US"] = None
    with pytest.raises(ValueError, match="different"):
        build_daily_report(*args, report_date="2026-11-01")


def test_invalid_ohlc_bars_are_visible_instead_of_silently_clean():
    args = inputs()
    rows = args[0]["history"]["BABA.US"]["data"]["candlesticks"]
    rows.append(
        {"timestamp": "1793246400", "open": "100", "close": "101", "high": "99", "low": "98"}
    )
    refresh_provenance(args)
    result = build_daily_report(*args, report_date="2026-11-01")
    assert result["data"]["omitted_bars"] == {"BABA.US": 1}
    assert not result["data"]["complete"]


def test_missing_provenance_cannot_bypass_matching_input_validation():
    args = inputs()
    args[1].pop("provenance", None)
    with pytest.raises(ValueError, match="provenance"):
        build_daily_report(*args, report_date="2026-11-01")
