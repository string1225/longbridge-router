"""Offline exposure controls; posthoc controls explain history, never generate orders."""

import argparse
import math
import statistics
from pathlib import Path

from research import fingerprint
from research.collect import save_json
from research.wave_lab import TEST_END, TEST_START, _metrics, _Portfolio, normalize_bars

VARIANTS = ("grid_3", "grid_5", "grid_8", "reversal_5", "trend_20_5")


def constant_weight(bars, weight, *, fee_rate, capital=100000):
    """Monthly fixed target with the existing engine's fills, fees and 1% dust rule."""
    if not math.isfinite(weight) or not 0 <= weight <= 1:
        raise ValueError("weight must be finite in [0,1]")
    if not math.isfinite(fee_rate) or not 0 <= fee_rate < 1:
        raise ValueError("fee_rate must be finite in [0,1)")
    if not bars:
        raise ValueError("completed bars required")
    portfolio = _Portfolio(capital, 0, fee_rate, [])
    histories, previous = [], capital
    for i, bar in enumerate(bars):
        prior = bars[i - 1] if i else None
        if prior is None or (bar.date.year, bar.date.month) != (prior.date.year, prior.date.month):
            portfolio.execute(
                bar,
                {
                    "target_weight": weight,
                    "signal_date": prior.date.isoformat() if prior else None,
                    "reason": "monthly_calendar_rebalance" if prior else "initial",
                },
                bounded=False,
            )
        equity = portfolio.cash + portfolio.shares * bar.close
        histories.append(
            {
                "date": bar.date.isoformat(),
                "open": bar.open,
                "close": bar.close,
                "cash": portfolio.cash,
                "shares": portfolio.shares,
                "equity": equity,
                "stock_exposure": portfolio.shares * bar.close / equity,
                "daily_return": equity / previous - 1,
            }
        )
        previous = equity
    return {
        "metrics": _metrics(histories, portfolio.trades, capital),
        "histories": histories,
        "trades": portfolio.trades,
    }


def calibrate_weight(bars, desired_exposure, *, fee_rate):
    """Ex-post descriptive control, using test mean exposure. This is lookahead.

    Dust suppression creates discontinuities: retain the closest solution and
    publish its signed residual rather than claiming an exact match.
    """
    if not math.isfinite(desired_exposure) or not 0 <= desired_exposure <= 1:
        raise ValueError("desired_exposure must be finite in [0,1]")
    lower, upper, best = 0.0, 1.0, None
    for weight in (0.0, 1.0):
        simulation = constant_weight(bars, weight, fee_rate=fee_rate)
        error = simulation["metrics"]["mean_exposure"] - desired_exposure
        candidate = {
            "target_weight": weight,
            "exposure_error": error,
            "uses_test_period_information": True,
            "simulation": simulation,
        }
        if best is None or abs(error) < abs(best["exposure_error"]):
            best = candidate
    for _ in range(36):
        weight = (lower + upper) / 2
        simulation = constant_weight(bars, weight, fee_rate=fee_rate)
        error = simulation["metrics"]["mean_exposure"] - desired_exposure
        if abs(error) < abs(best["exposure_error"]):
            best = {
                "target_weight": weight,
                "exposure_error": error,
                "uses_test_period_information": True,
                "simulation": simulation,
            }
        if error < 0:
            lower = weight
        else:
            upper = weight
    return best


def build_exposure_report(dataset, universe, wave):
    provenance = {
        "history_fingerprint": fingerprint(dataset.get("history", {})),
        "universe_fingerprint": fingerprint(universe),
    }
    if wave.get("provenance") != provenance:
        raise ValueError("different simulation provenance; rerun wave_lab")
    groups = {
        item["symbol"]: item.get("issuer_group", item["symbol"])
        for item in universe["volatility_candidates"]
    }
    stocks, omitted = {}, []
    for symbol in wave["aggregate"]["eligible_symbols"]:
        stock = wave["stocks"][symbol]
        periods = stock["periods"]
        if "training" not in periods or "temporal_test" not in periods:
            omitted.append(symbol)
            continue
        sample = [
            bar
            for bar in normalize_bars(dataset["history"][symbol], symbol=symbol)
            if TEST_START <= bar.date <= TEST_END
        ]
        stocks[symbol] = {}
        for variant in VARIANTS:
            observed = periods["temporal_test"]["strategies"][variant]["metrics"]
            weight = periods["training"]["strategies"][variant]["metrics"]["mean_exposure"]
            training = constant_weight(sample, weight, fee_rate=stock["fee_rate"])
            posthoc = calibrate_weight(
                sample, observed["mean_exposure"], fee_rate=stock["fee_rate"]
            )
            stocks[symbol][variant] = {
                "strategy": observed,
                "training_control": {
                    "target_weight": weight,
                    "uses_test_period_information": False,
                    "metrics": training["metrics"],
                },
                "posthoc_control": {k: v for k, v in posthoc.items() if k != "simulation"}
                | {"metrics": posthoc["simulation"]["metrics"]},
            }
    aggregates = {}
    for variant in VARIANTS:
        rows = [stock[variant] for stock in stocks.values()]
        if not rows:
            continue
        summary = {"listing_count": len(rows)}
        for label in ("strategy", "training_control", "posthoc_control"):
            metrics = [row[label] if label == "strategy" else row[label]["metrics"] for row in rows]
            summary[label] = {
                "mean_" + field: statistics.fmean(m[field] for m in metrics)
                for field in ("return", "max_drawdown", "mean_exposure", "trade_count")
            }
        for control in ("training_control", "posthoc_control"):
            excess = {
                symbol: stock[variant]["strategy"]["return"]
                - stock[variant][control]["metrics"]["return"]
                for symbol, stock in stocks.items()
            }
            issuer_values = {}
            for symbol, value in excess.items():
                issuer_values.setdefault(groups[symbol], []).append(value)
            summary["mean_excess_vs_" + control] = statistics.fmean(excess.values())
            summary["issuer_mean_excess_vs_" + control] = statistics.fmean(
                statistics.fmean(values) for values in issuer_values.values()
            )
            summary["beat_" + control + "_count"] = sum(v > 0 for v in excess.values())
        summary["max_posthoc_exposure_error"] = max(
            abs(row["posthoc_control"]["exposure_error"]) for row in rows
        )
        aggregates[variant] = summary
    return {
        "schema_version": 1,
        "provenance": provenance,
        "methodology": {
            "period": "2025-11-01..2026-10-30, already-inspected historical test",
            "training_control": "Per-symbol monthly target fixed at that rule's 2021-11-01.."
            "2025-10-31 mean stock exposure. Only training data chooses target. Realized "
            "test exposure may differ; not an exact risk match.",
            "posthoc_control": "Per-symbol monthly fixed target calibrated with future test "
            "mean exposure. Descriptive hindsight control, NOT an executable strategy or "
            "unseen validation. Matching mean exposure does not match pathwise risk/beta.",
            "accounting": "Existing next-open monthly calendar, proportional fees, fractional "
            "shares, initial fee, 1%-NAV dust rule, no terminal liquidation. No leverage.",
            "issuer_average": "Equal mean within each issuer, then equal mean across issuers; "
            "Alibaba ADR/HK counted as one issuer. Cross-sectional, not an FX-pooled portfolio.",
            "limitations": "No minimum fees/lot rounding/tax/FX/cash interest. Posthoc matching "
            "can leave residual due to dust discontinuities; publish maximum error. "
            "This experiment does not prove alpha or change frozen forward trading rules.",
        },
        "stocks": stocks,
        "omitted_symbols": omitted,
        "aggregate": {
            "listing_count": len(stocks),
            "issuer_count": len({groups[s] for s in stocks}),
            "variants": aggregates,
        },
    }


def main():
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--wave", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def read(path):
        return json.loads(path.read_text(encoding="utf-8-sig"))

    report = build_exposure_report(read(args.input), read(args.universe), read(args.wave))
    save_json(args.output, report)
    print(json.dumps(report["aggregate"], indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
