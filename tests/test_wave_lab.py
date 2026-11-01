"""Price-only experiments: temporal isolation, executable accounting and pool separation."""

import json
import math
import subprocess
import sys
from datetime import date, timedelta

import pytest

try:
    from research import wave_lab
except ImportError:
    wave_lab = None


def engine():
    assert wave_lab is not None, "The isolated price-only research engine is not implemented"
    return wave_lab


def test_new_observations_go_to_separate_forward_paper_period():
    lab = engine()
    rows = training_rows() + candles([100, 110, 90], start="2026-11-02")
    result = lab.build_report(
        {"history": {"TEST.US": {"data": {"candlesticks": rows}}}},
        {"volatility_candidates": [{"symbol": "TEST.US"}]},
    )
    stock = result["stocks"]["TEST.US"]
    assert stock["periods"]["forward_paper"]["start"] == "2026-11-02"
    assert "temporal_test" not in stock["periods"]
    assert result["aggregate"]["periods"]["forward_paper"]["stock_count"] == 1
    assert result["provenance"]["history_fingerprint"]


def candles(closes, start="2025-01-01", opens=None, highs=None):
    first = date.fromisoformat(start)
    return [
        {
            "timestamp": str(first + timedelta(days=i)),
            "open": str(opens[i] if opens else close),
            "close": str(close),
            "high": str(highs[i] if highs else max(close, opens[i] if opens else close)),
            "low": str(min(close, opens[i] if opens else close)),
        }
        for i, close in enumerate(closes)
    ]


def simulate(rows, variant="half_hold", fee_rate=0.001, **kwargs):
    lab = engine()
    return lab.simulate(
        lab.normalize_bars({"data": {"candlesticks": rows}}), variant, fee_rate=fee_rate, **kwargs
    )


def training_rows(volatile=True):
    closes = [100.0]
    for i in range(140):
        closes.append(closes[-1] * (1 + (0.04 if volatile else 0.001) * (-1) ** i))
    return candles(closes, start="2025-01-01")


def test_missing_high_low_are_rejected_instead_of_fabricated_for_breakouts():
    row = candles([100])[0]
    del row["high"]
    assert engine().normalize_bars([row]) == []


def test_normalization_sorts_dictionary_bars_and_keeps_last_valid_duplicate():
    lab = engine()
    rows = candles([101, 102, 103])
    duplicate = dict(rows[0], close="104", high="104")
    raw = {
        "code": 0,
        "data": {
            "candlesticks": {
                "second": rows[1],
                "first": rows[0],
                "duplicate": duplicate,
                "invalid_duplicate": dict(rows[0], close="NaN"),
                "third": rows[2],
            }
        },
    }
    bars = lab.normalize_bars(raw)
    assert [bar.date.isoformat() for bar in bars] == ["2025-01-01", "2025-01-02", "2025-01-03"]
    assert [bar.close for bar in bars] == [104, 102, 103]
    keyed_by_date = {
        row["timestamp"]: {k: v for k, v in row.items() if k != "timestamp"} for row in rows
    }
    assert len(lab.normalize_bars({"data": {"candlesticks": keyed_by_date}})) == 3
    assert lab.normalize_bars(None) == []
    assert lab.normalize_bars({"code": 100, "data": {"candlesticks": rows}}) == []


@pytest.mark.parametrize(
    "symbol,stamp", [("601398.SH", 1698768000), ("941.HK", 1698768000000), ("NVDA.US", 1698811200)]
)
def test_daily_numeric_timestamp_uses_exchange_date_instead_of_previous_utc_date(symbol, stamp):
    lab = engine()
    row = dict(candles([100])[0], timestamp=str(stamp))
    bars = lab.normalize_bars({"data": {"symbol": symbol, "candlesticks": [row]}})
    assert bars[0].date.isoformat() == "2023-11-01"
    direct = lab.normalize_bars([row], symbol=symbol)
    assert direct[0].date.isoformat() == "2023-11-01"
    report = lab.build_report(
        {"history": {symbol: {"data": {"candlesticks": [row]}}}},
        {"volatility_candidates": [{"symbol": symbol}]},
    )
    assert report["stocks"][symbol]["first_date"] == "2023-11-01"
    # An explicit source trading date takes priority over the timestamp representation.
    explicit = lab.normalize_bars([dict(row, date="2023-11-02")], symbol=symbol)
    assert explicit[0].date.isoformat() == "2023-11-02"


def test_signal_fills_at_next_open_and_never_final_close():
    rows = candles([100, 106, 100], opens=[100, 100, 120])
    result = simulate(rows, "grid_5", fee_rate=0)
    assert len(result["trades"]) == 2
    trade = result["trades"][1]
    assert trade["signal_date"] == "2025-01-02"
    assert trade["date"] == "2025-01-03"
    assert trade["price"] == 120
    assert trade["side"] == "sell"
    assert trade["notional"] == pytest.approx(10300)
    assert result["histories"][1]["shares"] == 500
    assert all(t["signal_date"] < t["date"] for t in result["trades"][1:])


@pytest.mark.parametrize(
    "variant",
    [
        "full_hold",
        "half_hold",
        "monthly_50",
        "grid_3",
        "grid_5",
        "grid_8",
        "reversal_5",
        "trend_20_5",
    ],
)
def test_future_prices_do_not_change_past_signals_or_fills(variant):
    prefix = candles([100] * 20 + [106, 101, 95, 110], start="2025-01-10")
    future = candles([800, 1, 1000], start="2025-02-03")
    short = simulate(prefix, variant)
    long = simulate(prefix + future, variant)
    assert short["histories"] == long["histories"][: len(prefix)]
    assert short["trades"] == [t for t in long["trades"] if t["date"] <= "2025-02-02"]
    assert short["signals"] == [s for s in long["signals"] if s["signal_date"] <= "2025-02-02"]


@pytest.mark.parametrize("variant,weight", [("full_hold", 1.0), ("half_hold", 0.5)])
def test_hold_matches_fractional_shares_arithmetic_with_initial_fee(variant, weight):
    result = simulate(candles([100, 120], opens=[100, 110]), variant)
    shares = weight * 100000 / (100 * (1 + weight * 0.001))
    cash = 100000 - shares * 100 * 1.001
    expected_final = cash + shares * 120
    assert result["histories"][-1]["equity"] == pytest.approx(expected_final)
    assert result["metrics"]["return"] == pytest.approx(expected_final / 100000 - 1)
    assert result["metrics"]["costs"] == pytest.approx(shares * 100 * 0.001)
    assert result["metrics"]["trade_count"] == 1
    assert result["histories"][0]["stock_exposure"] == pytest.approx(weight)


@pytest.mark.parametrize("variant", ["grid_3", "grid_5", "grid_8", "reversal_5", "trend_20_5"])
def test_orders_pay_fees_from_cash_and_cannot_borrow_or_short(variant):
    closes = [100 * (1.12**i if i < 30 else 1.12**29 * 0.85 ** (i - 29)) for i in range(60)]
    rows = candles(closes)
    result = simulate(rows, variant, fee_rate=0.02)
    histories = result["histories"]
    trades = result["trades"]
    assert len(trades) > 1
    assert all(row["cash"] >= -1e-8 and row["shares"] >= -1e-8 for row in histories)
    assert sum(trade["fee"] for trade in trades) == pytest.approx(result["metrics"]["costs"])
    assert all(trade["fee"] == pytest.approx(trade["notional"] * 0.02) for trade in trades)
    shares, cash = 0.0, 100000.0
    by_date = {}
    for trade in trades:
        signed = trade["notional"] if trade["side"] == "buy" else -trade["notional"]
        shares += signed / trade["price"]
        cash -= signed + trade["fee"]
        by_date[trade["date"]] = (shares, cash)
        if trade["reason"] != "initial":
            assert 0.2 - 1e-9 <= trade["stock_exposure_after"] <= 0.8 + 1e-9
            assert trade["notional"] >= 0.01 * trade["equity_before"] - 1e-8
    for row in histories:
        if row["date"] in by_date:
            expected_shares, expected_cash = by_date[row["date"]]
            assert row["shares"] == pytest.approx(expected_shares)
            assert row["cash"] == pytest.approx(expected_cash)


def test_subminimum_orders_are_suppressed_instead_of_costly_dust_trades():
    # At the upper bound after repeated 10% orders, the residual permitted order is tiny.
    result = simulate(candles([100 * 0.94**i for i in range(30)]), "grid_5", fee_rate=0)
    assert len(result["trades"]) > 2
    assert all(t["notional"] >= t["equity_before"] * 0.01 - 1e-8 for t in result["trades"])


def test_trend_breakout_uses_prior_twenty_highs_and_trails_closes():
    closes = [100] * 20 + [102, 110, 104, 100]
    highs = [101] * 20 + [200, 200, 200, 200]
    result = simulate(candles(closes, highs=highs), "trend_20_5", fee_rate=0)
    trades = result["trades"]
    assert trades[1]["signal_date"] == "2025-01-21"
    assert trades[1]["date"] == "2025-01-22"
    assert trades[1]["reason"] == "prior_20_high_breakout"
    assert trades[1]["stock_exposure_after"] == pytest.approx(0.8)
    assert trades[2]["signal_date"] == "2025-01-23"
    assert trades[2]["date"] == "2025-01-24"
    assert trades[2]["reason"] == "trailing_close_5_stop"
    assert trades[2]["stock_exposure_after"] == pytest.approx(0.2)


def test_trailing_high_starts_on_entry_fill_day_not_before_the_position_enters():
    rows = candles(
        [100] * 20 + [110, 101, 105, 99, 98], opens=[100] * 20 + [100, 100, 102, 100, 98]
    )
    result = simulate(rows, "trend_20_5", fee_rate=0)
    stops = [t for t in result["trades"] if t["reason"] == "trailing_close_5_stop"]
    assert len(stops) == 1
    assert stops[0]["signal_date"] == "2025-01-24"
    assert stops[0]["date"] == "2025-01-25"
    assert stops[0]["price"] == 98


def test_temporal_test_can_use_prior_prices_for_warmup_but_starts_new_capital():
    rows = candles([100] * 25 + [102, 110], start="2025-10-07", highs=[101] * 25 + [150, 150])
    result = simulate(rows, "trend_20_5", fee_rate=0, start="2025-11-01", end="2026-10-30")
    assert len(result["histories"]) == 2
    assert result["trades"][0]["date"] == "2025-11-01"
    assert result["histories"][0]["equity"] == 100000
    assert result["trades"][1]["signal_date"] == "2025-11-01"
    assert result["trades"][1]["date"] == "2025-11-02"


def test_monthly_rebalance_uses_next_month_open_and_same_commission():
    rows = candles([100, 150, 120, 130], start="2025-01-30", opens=[100, 110, 140, 125])
    result = simulate(rows, "monthly_50", fee_rate=0.001)
    assert len(result["trades"]) == 2
    rebalance = result["trades"][1]
    assert rebalance["signal_date"] == "2025-01-31"
    assert rebalance["date"] == "2025-02-01"
    assert rebalance["price"] == 140
    assert rebalance["stock_exposure_after"] == pytest.approx(0.5)
    assert rebalance["fee"] == pytest.approx(rebalance["notional"] * 0.001)


def test_training_eligibility_does_not_use_test_prices_or_latest_metadata():
    lab = engine()
    training = training_rows(volatile=True)
    later_a = candles([100, 100, 100], start="2025-11-01")
    later_b = candles([1, 1000, 0.1], start="2025-11-01")
    a = lab.training_eligibility(lab.normalize_bars(training + later_a))
    b = lab.training_eligibility(lab.normalize_bars(training + later_b))
    assert a == b
    assert a["eligible"] is True
    assert a["return_count"] == 140
    assert a["annualized_volatility"] > 0.3
    low_vol = lab.training_eligibility(lab.normalize_bars(training_rows(volatile=False) + later_b))
    assert low_vol["eligible"] is False
    short = lab.training_eligibility(lab.normalize_bars(training[:126]))
    assert short["eligible"] is False
    assert short["reason"] == "fewer_than_126_training_returns"


def test_report_pool_conclusions_include_only_training_eligible_explicit_wave_candidates():
    lab = engine()
    wave = training_rows() + candles([100, 110, 108], start="2025-11-01")
    quiet = training_rows(False) + candles([100, 500, 1], start="2025-11-01")
    dividend_changed = {"symbol": "DIV.US", "dividend_yield": 0.99, "volatility": 99}
    dataset = {
        "history": {
            symbol: {"code": 0, "data": {"candlesticks": rows}}
            for symbol, rows in [("WAVE.US", wave), ("DIV.US", wave), ("QUIET.US", quiet)]
        },
        "quotes": {"result": {"data": {"securities": [dividend_changed]}}},
        "indexes": {"US": {"data": {"security_calc_index": [dividend_changed]}}},
    }
    dataset["history"]["MISSING.US"] = None
    universe = {
        "dividend_candidates": [{"symbol": "DIV.US", "name": "Dividend only"}],
        "volatility_candidates": [{"symbol": s} for s in ("WAVE.US", "QUIET.US", "MISSING.US")],
        "benchmarks": [],
    }
    report = lab.build_report(dataset, universe)
    assert report["aggregate"]["eligible_symbols"] == ["WAVE.US"]
    assert report["aggregate"]["eligible_wave_count"] == 1
    assert report["stocks"]["DIV.US"]["status"] == "excluded_dividend_only"
    assert report["stocks"]["MISSING.US"]["status"] == "missing_history"
    assert report["stocks"]["QUIET.US"]["eligibility"]["eligible"] is False
    aggregate = report["aggregate"]["periods"]["temporal_test"]
    assert set(aggregate["variants"]) == set(lab.VARIANTS)
    assert aggregate["variants"]["grid_5"]["stock_count"] == 1
    assert sum(s["stock_count"] for s in aggregate["regime_slices"].values()) == 1
    assert "already-inspected" in report["methodology"]["temporal_test_caveat"]
    assert "dividend" in report["methodology"]["return_basis"].lower()
    assert "history" == report["methodology"]["inputs_used"][0]
    universe["volatility_candidates"].append({"symbol": "DIV.US"})
    overlap = lab.build_report(dataset, universe)
    assert overlap["aggregate"]["eligible_symbols"] == ["DIV.US", "WAVE.US"]


def test_cli_writes_strict_json_with_fixed_variants_and_missing_data(tmp_path):
    lab = engine()
    dataset = tmp_path / "dataset.json"
    universe = tmp_path / "universe.json"
    output = tmp_path / "output.json"
    dataset.write_text(json.dumps({"history": {"BAD.US": None}}), encoding="utf-8")
    universe.write_text(
        json.dumps({"volatility_candidates": [{"symbol": "BAD.US"}]}), encoding="utf-8"
    )
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "research.wave_lab",
            "--input",
            str(dataset),
            "--universe",
            str(universe),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["aggregate"]["eligible_wave_count"] == 0
    assert report["stocks"]["BAD.US"]["status"] == "missing_history"
    assert set(report["methodology"]["fixed_variants"]) == set(lab.VARIANTS)
    assert "eligible" in process.stdout.lower()
    assert "grid_5" in process.stdout
    assert "BAD.US" in process.stdout
    assert "temporal_test" in process.stdout
    assert "NaN" not in output.read_text(encoding="utf-8")


def test_metrics_drawdown_include_initial_cost_and_remain_finite():
    result = simulate(candles([100, 80, 120]), "full_hold", fee_rate=0.001)
    expected_dd = 80 / 100 / 1.001 - 1
    assert result["metrics"]["max_drawdown"] == pytest.approx(expected_dd)
    assert all(
        math.isfinite(result["metrics"][key])
        for key in ("return", "cagr", "max_drawdown", "mean_exposure", "costs")
    )


def test_market_fee_assumptions_apply_to_every_variant_and_benchmarks_are_separate():
    lab = engine()
    rows = training_rows() + candles([100, 120], start="2025-11-01")
    dataset = {
        "history": {
            s: {"data": {"candlesticks": rows}}
            for s in ("00005.HK", "600000.SH", "WAVE.US", "SPY.US")
        }
    }
    universe = {
        "volatility_candidates": [{"symbol": s} for s in ("00005.HK", "600000.SH", "WAVE.US")],
        "benchmarks": [{"symbol": "SPY.US"}],
    }
    report = lab.build_report(dataset, universe)
    assert report["stocks"]["00005.HK"]["fee_rate"] == 0.0025
    assert report["stocks"]["600000.SH"]["fee_rate"] == 0.001
    assert report["stocks"]["WAVE.US"]["fee_rate"] == 0.001
    assert "SPY.US" not in report["aggregate"]["eligible_symbols"]
    assert set(report["stocks"]["SPY.US"]["periods"]["temporal_test"]["strategies"]) == set(
        lab.BASELINES
    )
    for stock in report["stocks"].values():
        for variant in stock["periods"]["temporal_test"]["strategies"].values():
            for trade in variant["trades"]:
                assert trade["fee"] == pytest.approx(trade["notional"] * stock["fee_rate"])
    by_market = report["aggregate"]["periods"]["temporal_test"]["by_market"]
    assert set(by_market) == {"HK", "CN", "US"}
    assert all(item["stock_count"] == 1 for item in by_market.values())
    overridden = lab.build_report(dataset, universe, fee_rate=0)
    assert all(s["fee_rate"] == 0 for s in overridden["stocks"].values())
