"""Offline price-only experiments; this module never contacts the gateway or broker.

Run from the repository root with ``python -m research.wave_lab --help``.
Daily forward-adjusted OHLC must be supplied by the caller. Price returns are not
an independently reconstructed cash-dividend total return. All thresholds are
fixed experiments, including the previously inspected historical time split.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from research import fingerprint

TRAIN_END = date(2025, 10, 31)
TEST_START = date(2025, 11, 1)
TEST_END = date(2026, 10, 30)
PAPER_START = date(2026, 11, 2)
BASELINES = ("full_hold", "half_hold", "monthly_50")
VARIANTS = (*BASELINES, "grid_3", "grid_5", "grid_8", "reversal_5", "trend_20_5")
DEFAULT_COST_BPS = {"CN": 10.0, "HK": 25.0, "US": 10.0}


@dataclass(frozen=True)
class Bar:
    date: date
    open: float
    close: float
    high: float
    low: float


def _date(value: Any, *, hour_offset: int = 0) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        stamp = float(text)
    except ValueError:
        return date.fromisoformat(text[:10])
    if abs(stamp) >= 1e12:
        stamp /= 1000
    return (datetime.fromtimestamp(stamp, UTC) + timedelta(hours=hour_offset)).date()


def normalize_bars(raw: Any, *, symbol: str | None = None) -> list[Bar]:
    """Unwrap saved gateway responses; sort and retain the last valid bar per date.

    Lists, dictionaries keyed by a row id/date, HTTP ``result`` wrappers and
    direct candles are accepted. Invalid/failed records are omitted. No missing
    day or OHLC value is synthesized. Explicit row
    trading dates take priority. Numeric CN/HK timestamps use the exchange's
    UTC+8 date, avoiding a previous-UTC-date error at local midnight; US daily
    timestamps retain their UTC day. Pass symbol when the envelope omits it.
    """
    for _ in range(8):
        if not isinstance(raw, dict):
            break
        symbol = symbol or raw.get("symbol")
        if raw.get("code", 0) not in (0, "0", None):
            return []
        if isinstance(raw.get("http"), int) and raw["http"] >= 400:
            return []
        key = next((key for key in ("result", "data", "candlesticks") if key in raw), None)
        if key is None:
            break
        raw = raw[key]
    if isinstance(raw, dict):
        if "open" in raw and "close" in raw:
            items = [(None, raw)]
        else:
            items = list(raw.items())
    elif isinstance(raw, list):
        items = [(None, row) for row in raw]
    else:
        return []
    by_date = {}
    hour_offset = 8 if _market(symbol or "") in ("CN", "HK") else 0
    for key, row in items:
        if not isinstance(row, dict):
            continue
        try:
            day = _date(row.get("date", row.get("timestamp", key)), hour_offset=hour_offset)
            opening, closing = float(row["open"]), float(row["close"])
            high, low = float(row["high"]), float(row["low"])
            if not all(math.isfinite(v) and v > 0 for v in (opening, closing, high, low)):
                continue
            if high < max(opening, closing) or low > min(opening, closing) or high < low:
                continue
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            continue
        by_date[day] = Bar(day, opening, closing, high, low)
    return sorted(by_date.values(), key=lambda bar: bar.date)


def training_eligibility(bars: list[Bar]) -> dict[str, Any]:
    """Selection uses only pre-2025-11-01 closes, never quote/index metadata."""
    training = [bar for bar in bars if bar.date <= TRAIN_END]
    returns = [
        current.close / prior.close - 1
        for prior, current in zip(training, training[1:], strict=False)
    ]
    volatility = statistics.stdev(returns) * math.sqrt(252) if len(returns) >= 2 else None
    enough = len(returns) >= 126
    eligible = enough and volatility is not None and volatility >= 0.30
    return {
        "eligible": eligible,
        "reason": (
            "eligible"
            if eligible
            else "fewer_than_126_training_returns"
            if not enough
            else "training_volatility_below_30_percent"
        ),
        "return_count": len(returns),
        "annualized_volatility": volatility,
        "training_first_date": training[0].date.isoformat() if training else None,
        "training_last_date": training[-1].date.isoformat() if training else None,
    }


@dataclass
class _Portfolio:
    cash: float
    shares: float
    fee_rate: float
    trades: list[dict[str, Any]]

    def execute(self, bar: Bar, order: dict[str, Any], bounded: bool) -> bool:
        stock = self.shares * bar.open
        equity = self.cash + stock
        target = order.get("target_weight")
        if target is not None:
            difference = target * equity - stock
            delta = difference / (
                1 + target * self.fee_rate if difference >= 0 else 1 - target * self.fee_rate
            )
        else:
            delta = order["notional"] * (1 if order["side"] == "buy" else -1)
        if delta > 0:
            limit = self.cash / (1 + self.fee_rate)
            if bounded:
                limit = min(limit, max(0.0, (0.8 * equity - stock) / (1 + 0.8 * self.fee_rate)))
            delta = min(delta, limit)
        elif delta < 0:
            limit = stock
            if bounded:
                limit = min(limit, max(0.0, (stock - 0.2 * equity) / (1 - 0.2 * self.fee_rate)))
            delta = -min(-delta, limit)
        notional = abs(delta)
        if notional < equity * 0.01 - 1e-8 or notional <= 1e-10:
            return False
        fee = notional * self.fee_rate
        self.shares += delta / bar.open
        self.cash -= delta + fee
        # Exact full allocation may leave a tiny negative floating-point residual.
        if -1e-8 < self.cash < 0:
            self.cash = 0.0
        if self.cash < -1e-8 or self.shares < -1e-8:
            raise ArithmeticError("Order would borrow cash or short shares")
        after = self.cash + self.shares * bar.open
        self.trades.append(
            {
                "date": bar.date.isoformat(),
                "signal_date": order["signal_date"],
                "side": "buy" if delta > 0 else "sell",
                "price": bar.open,
                "notional": notional,
                "shares": notional / bar.open,
                "fee": fee,
                "reason": order["reason"],
                "equity_before": equity,
                "stock_exposure_after": self.shares * bar.open / after,
            }
        )
        return True


def _metrics(histories: list[dict], trades: list[dict], capital: float) -> dict:
    final = histories[-1]["equity"]
    total_return = final / capital - 1
    days = max(1, (_date(histories[-1]["date"]) - _date(histories[0]["date"])).days + 1)
    log_growth = math.log(final / capital) * 365.25 / days
    # A one-day extreme sample cannot sensibly be annualized into finite JSON.
    cagr = math.expm1(log_growth) if log_growth < 709 else None
    peak, drawdown = capital, 0.0
    for row in histories:
        peak = max(peak, row["equity"])
        drawdown = min(drawdown, row["equity"] / peak - 1)
    return {
        "initial_equity": capital,
        "final_equity": final,
        "return": total_return,
        "cagr": cagr,
        "max_drawdown": drawdown,
        "trade_count": len(trades),
        "mean_exposure": statistics.fmean(row["stock_exposure"] for row in histories),
        "costs": sum(trade["fee"] for trade in trades),
        "cost_fraction_initial_equity": sum(trade["fee"] for trade in trades) / capital,
    }


def simulate(
    bars: list[Bar],
    variant: str,
    *,
    start: str | date | None = None,
    end: str | date | None = None,
    fee_rate: float = 0.001,
    capital: float = 100000,
) -> dict[str, Any]:
    """Use prior/current closes for signals, then fill at the next observed open.

    Each period starts new capital at its first open; earlier bars provide
    indicator warmup only. Grid anchors reset to the execution open after an
    actual fill; one 10%-of-signal-NAV order per close. Bounds constrain orders;
    passive overnight/intraday movement can carry exposure outside 20%-80%.
    """
    if variant not in VARIANTS:
        raise ValueError(f"Unknown fixed variant: {variant}")
    if not math.isfinite(fee_rate) or not 0 <= fee_rate < 1:
        raise ValueError("fee_rate must be finite in [0, 1)")
    if not math.isfinite(capital) or capital <= 0:
        raise ValueError("capital must be positive and finite")
    lower, upper = _date(start) if start else date.min, _date(end) if end else date.max
    indices = [i for i, bar in enumerate(bars) if lower <= bar.date <= upper]
    if not indices:
        return {"status": "no_period_bars", "metrics": None, "histories": [], "trades": []}
    portfolio = _Portfolio(capital, 0.0, fee_rate, [])
    histories, signals = [], []
    first = bars[indices[0]]
    portfolio.execute(
        first,
        {
            "target_weight": 1.0 if variant == "full_hold" else 0.5,
            "signal_date": None,
            "reason": "initial",
        },
        bounded=False,
    )
    anchor, pending, trend_active, trend_peak = first.open, None, False, None
    previous_equity = capital
    for position, index in enumerate(indices):
        bar = bars[index]
        if pending is not None:
            filled = portfolio.execute(bar, pending, bounded=variant not in BASELINES)
            if filled and variant.startswith("grid_"):
                anchor = bar.open
            pending = None
        if position and variant == "monthly_50":
            prior = bars[indices[position - 1]]
            if (bar.date.year, bar.date.month) != (prior.date.year, prior.date.month):
                portfolio.execute(
                    bar,
                    {
                        "target_weight": 0.5,
                        "signal_date": prior.date.isoformat(),
                        "reason": "monthly_calendar_rebalance",
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
                "daily_return": equity / previous_equity - 1,
            }
        )
        previous_equity = equity
        if variant.startswith("grid_"):
            step = int(variant.split("_")[1]) / 100
            movement = bar.close / anchor - 1
            if movement >= step - 1e-12 or movement <= -step + 1e-12:
                pending = {
                    "side": "sell" if movement > 0 else "buy",
                    "notional": equity * 0.1,
                    "signal_date": bar.date.isoformat(),
                    "reason": f"grid_{step:.0%}",
                }
        elif variant == "reversal_5" and index:
            movement = bar.close / bars[index - 1].close - 1
            if movement >= 0.05 - 1e-12 or movement <= -0.05 + 1e-12:
                pending = {
                    "side": "sell" if movement > 0 else "buy",
                    "notional": equity * 0.1,
                    "signal_date": bar.date.isoformat(),
                    "reason": "daily_close_5_reversal",
                }
        elif variant == "trend_20_5":
            if trend_active:
                trend_peak = bar.close if trend_peak is None else max(trend_peak, bar.close)
                if bar.close <= trend_peak * 0.95 + 1e-12:
                    pending = {
                        "target_weight": 0.2,
                        "signal_date": bar.date.isoformat(),
                        "reason": "trailing_close_5_stop",
                    }
                    trend_active, trend_peak = False, None
            elif index >= 20 and bar.close > max(prior.high for prior in bars[index - 20 : index]):
                pending = {
                    "target_weight": 0.8,
                    "signal_date": bar.date.isoformat(),
                    "reason": "prior_20_high_breakout",
                }
                # The allocation enters at the following open. Its first observed
                # close, rather than a close before entry, starts the trailing peak.
                trend_active, trend_peak = True, None
        if pending:
            signals.append(dict(pending))
    return {
        "status": "ok",
        "start": first.date.isoformat(),
        "end": bars[indices[-1]].date.isoformat(),
        "bar_count": len(histories),
        "metrics": _metrics(histories, portfolio.trades, capital),
        "histories": histories,
        "trades": portfolio.trades,
        "signals": signals,
        "unfilled_final_signal": pending,
    }


def _market(symbol: str) -> str:
    suffix = symbol.rsplit(".", 1)[-1].upper()
    return (
        "CN" if suffix in ("SH", "SZ", "CN", "BJ") else suffix if suffix in ("US", "HK") else "US"
    )


def _regime(bars: list[Bar]) -> dict[str, Any]:
    change = bars[-1].close / bars[0].open - 1
    return {
        "label": "rising" if change >= 0.10 else "falling" if change <= -0.10 else "sideways",
        "underlying_open_to_close_return": change,
        "ex_post_descriptive_only": True,
    }


def _aggregate_variants(stocks: dict, symbols: list[str], period: str) -> dict:
    result = {}
    for variant in VARIANTS:
        available = [
            stocks[s]["periods"][period]["strategies"][variant]["metrics"]
            for s in symbols
            if period in stocks[s].get("periods", {})
            and variant in stocks[s]["periods"][period]["strategies"]
        ]
        summaries = {"stock_count": len(available)}
        for field in (
            "return",
            "cagr",
            "max_drawdown",
            "trade_count",
            "mean_exposure",
            "cost_fraction_initial_equity",
        ):
            values = [m[field] for m in available if m[field] is not None]
            summaries[f"mean_{field}"] = statistics.fmean(values) if values else None
        summaries["median_return"] = (
            statistics.median(m["return"] for m in available) if available else None
        )
        for baseline in BASELINES:
            paired = [
                (
                    stocks[s]["periods"][period]["strategies"][variant]["metrics"]["return"],
                    stocks[s]["periods"][period]["strategies"][baseline]["metrics"]["return"],
                )
                for s in symbols
                if period in stocks[s].get("periods", {})
                and variant in stocks[s]["periods"][period]["strategies"]
            ]
            summaries[f"beat_{baseline}_count"] = sum(
                value > reference for value, reference in paired
            )
            summaries[f"mean_excess_return_vs_{baseline}"] = (
                statistics.fmean(value - reference for value, reference in paired)
                if paired
                else None
            )
        result[variant] = summaries
    return result


def _aggregate(stocks: dict, symbols: list[str]) -> dict:
    periods = {}
    for period in ("training", "temporal_test", "forward_paper"):
        available = [s for s in symbols if period in stocks[s].get("periods", {})]
        slices = {}
        for regime in ("rising", "falling", "sideways"):
            members = [
                s for s in available if stocks[s]["periods"][period]["regime"]["label"] == regime
            ]
            slices[regime] = {
                "stock_count": len(members),
                "symbols": members,
                "variants": _aggregate_variants(stocks, members, period),
            }
        markets = {}
        for market in sorted({stocks[s]["market"] for s in available}):
            members = [s for s in available if stocks[s]["market"] == market]
            markets[market] = {
                "stock_count": len(members),
                "symbols": members,
                "variants": _aggregate_variants(stocks, members, period),
            }
        periods[period] = {
            "stock_count": len(available),
            "symbols": available,
            "variants": _aggregate_variants(stocks, available, period),
            "regime_slices": slices,
            "by_market": markets,
        }
    return {
        "eligible_wave_count": len(symbols),
        "eligible_symbols": symbols,
        "periods": periods,
        "interpretation": "Cross-sectional averages of normalized per-stock experiments; "
        "not a pooled or investable cross-currency portfolio; no FX conversion.",
    }


def build_report(dataset: dict, universe: dict, *, fee_rate: float | None = None) -> dict:
    """Build auditable per-stock results and fixed-variant eligible-wave summaries."""
    entries, roles = {}, {}
    for source, role in (
        ("dividend_candidates", "dividend"),
        ("volatility_candidates", "volatility"),
        ("benchmarks", "benchmark"),
    ):
        for entry in universe.get(source, []):
            if isinstance(entry, str):
                entry = {"symbol": entry}
            if not isinstance(entry, dict) or not entry.get("symbol"):
                continue
            symbol = entry["symbol"]
            entries[symbol] = {**entries.get(symbol, {}), **entry}
            roles.setdefault(symbol, set()).add(role)
    costs = {**DEFAULT_COST_BPS, **universe.get("default_cost_bps_by_market", {})}
    stocks = {}
    for symbol in sorted(entries):
        bars = normalize_bars(dataset.get("history", {}).get(symbol), symbol=symbol)
        market = _market(symbol)
        rate = fee_rate if fee_rate is not None else float(costs[market]) / 10000
        stock = {
            "name": entries[symbol].get("name", symbol),
            "roles": sorted(roles[symbol]),
            "market": market,
            "currency": {"CN": "CNY", "HK": "HKD", "US": "USD"}[market],
            "fee_rate": rate,
            "bar_count": len(bars),
            "eligibility": training_eligibility(bars),
            "periods": {},
        }
        stocks[symbol] = stock
        if not bars:
            stock["status"] = "missing_history"
            continue
        stock["first_date"], stock["last_date"] = (
            bars[0].date.isoformat(),
            bars[-1].date.isoformat(),
        )
        if "volatility" not in roles[symbol] and "benchmark" not in roles[symbol]:
            stock["status"] = "excluded_dividend_only"
            continue
        stock["status"] = "ok"
        variants = VARIANTS if "volatility" in roles[symbol] else BASELINES
        for period, start, end in (
            ("training", date.min, TRAIN_END),
            ("temporal_test", TEST_START, TEST_END),
            ("forward_paper", PAPER_START, date.max),
        ):
            selected = [bar for bar in bars if start <= bar.date <= end]
            if not selected:
                continue
            stock["periods"][period] = {
                "bar_count": len(selected),
                "start": selected[0].date.isoformat(),
                "end": selected[-1].date.isoformat(),
                "regime": _regime(selected),
                "strategies": {
                    variant: simulate(bars, variant, start=start, end=end, fee_rate=rate)
                    for variant in variants
                },
            }
    eligible = [
        symbol
        for symbol, stock in stocks.items()
        if "volatility" in stock["roles"] and stock["eligibility"]["eligible"]
    ]
    return {
        "schema_version": 1,
        "provenance": {
            "history_fingerprint": fingerprint(dataset.get("history", {})),
            "universe_fingerprint": fingerprint(universe),
        },
        "methodology": {
            "purpose": "Offline fixed-rule price-only volatility-pool research",
            "inputs_used": ["history"],
            "ignored_inputs": ["quotes", "indexes", "dividend_yield", "cash_dividends"],
            "return_basis": "Supplied forward-adjusted daily OHLC price experiment; not an "
            "independent reconstruction of actual cash-dividend total return.",
            "temporal_test_caveat": "2025-11-01..2026-10-30 is an already-inspected historical "
            "sample, not virgin out-of-sample evidence. No threshold selection.",
            "training_end": TRAIN_END.isoformat(),
            "test_start": TEST_START.isoformat(),
            "test_end": TEST_END.isoformat(),
            "forward_paper_start": PAPER_START.isoformat(),
            "forward_paper": "Separate prospective indicative simulation from 2026-11-02; "
            "same predeclared variants and training-eligible cohort, recomputed from saved "
            "daily bars with revision tracking. Not executed orders. Future rule or cohort "
            "changes require an explicit protocol revision; do not relabel inspected history.",
            "fixed_variants": list(VARIANTS),
            "eligibility": "Explicit volatility candidate AND >=126 daily training returns AND "
            "sample stdev(simple training returns)*sqrt(252) >=30%; prices through "
            "2025-10-31 only. Dividend-only candidates and benchmarks excluded.",
            "default_cost_bps_by_market": costs,
            "global_fee_rate_override": fee_rate,
            "cost_model": "Assumed proportional cost each side, including initial purchase; "
            "HK 25bps / CN 10bps / US 10bps defaults are research assumptions, not broker quotes.",
            "execution": "Signal at close, fill next observed daily open; final signal unfilled. "
            "Monthly calendar rebalance at first next-month observed open. No terminal "
            "liquidation. Fractional shares, no leverage/shorting. Orders below 1% of "
            "execution-time NAV suppressed; costs debited from cash.",
            "initialization": "Each period restarts 100000 local-currency units at its first open. "
            "Initial target is 50% stock on post-fee NAV (full_hold 100%). "
            "Pre-period prices supply indicators only, with no carried signals or positions.",
            "grid": "Fixed 3/5/8% close-to-anchor threshold; contrarian 10% of signal-time NAV; "
            "anchor starts at initial open and resets only at actual execution opens. One "
            "order per signal day; no intra-bar level fills.",
            "reversal": "Daily close change >=+5% sells 10% signal NAV; <=-5% buys 10% signal NAV.",
            "trend": "Close strictly above prior 20 daily HIGH values targets 80% stock next open. "
            "A 5% fall from highest close since the entry-fill day targets 20% next open. "
            "Current candle high excluded from breakout comparison.",
            "bounds": "Buy orders may not increase post-fee stock weight above 80%; sell orders "
            "may not reduce it below 20%. Passive market moves can drift outside the interval, "
            "including after a partial correcting order. No forced extra rebalance. "
            "Dust orders suppressed.",
            "regimes": "Ex-post per-stock period open-to-final-close price returns: rising>=10%, "
            "falling<=-10%, otherwise sideways; descriptive only, never signal inputs.",
            "metrics": "Returns are decimal fractions; max drawdown is negative and includes "
            "initial "
            "costs; CAGR uses inclusive actual calendar days; mean exposure is mean daily "
            "close stock weight; trade_count includes initial purchase. All comparisons "
            "use the same per-stock cost assumption. Cash earns zero interest.",
            "limitations": [
                "Candidate universe is hand-chosen, not a point-in-time complete universe; "
                "survivorship and selection bias remain.",
                "Forward-adjustment factors may use subsequently known corporate actions; "
                "adjusted prices are supplied inputs, not independently audited.",
                "No FX pooling, taxes, board-lot rounding, volume/liquidity limits, "
                "bid/ask path, minimum broker charges or trading suspensions modeled.",
                "Missing/invalid bars are omitted; next open means next supplied observed open.",
                "Annualization of short samples can be unstable; overflow reported as null.",
            ],
        },
        "stocks": stocks,
        "aggregate": _aggregate(stocks, eligible),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True, type=Path, help="Saved raw daily history dataset JSON"
    )
    parser.add_argument(
        "--universe", required=True, type=Path, help="Explicit separated-pool manifest JSON"
    )
    parser.add_argument("--output", required=True, type=Path, help="Result JSON file")
    parser.add_argument(
        "--fee-rate",
        type=float,
        default=None,
        help="Optional global per-side fee override, e.g. 0.001 for 10bps",
    )
    args = parser.parse_args()
    dataset = json.loads(args.input.read_text(encoding="utf-8-sig"))
    universe = json.loads(args.universe.read_text(encoding="utf-8-sig"))
    report = build_report(dataset, universe, fee_rate=args.fee_rate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        f"Saved {len(report['stocks'])} stocks; "
        f"{report['aggregate']['eligible_wave_count']} training-eligible wave candidates: "
        f"{args.output}"
    )
    for symbol, stock in report["stocks"].items():
        included = symbol in report["aggregate"]["eligible_symbols"]
        print(
            f"{symbol}: roles={','.join(stock['roles'])}; {stock['status']}; "
            f"eligible_wave={included}"
        )
    for period, result in report["aggregate"]["periods"].items():
        print(
            f"{period}: {result['stock_count']} eligible-wave stocks; "
            "cross-sectional statistics, not a pooled portfolio"
        )
        for variant, metrics in result["variants"].items():
            values = []
            for field in (
                "return",
                "cagr",
                "max_drawdown",
                "mean_exposure",
                "cost_fraction_initial_equity",
                "trade_count",
            ):
                value = metrics[f"mean_{field}"]
                values.append(f"{field}={value:.6f}" if value is not None else f"{field}=null")
            print(f"  {variant}: " + "; ".join(values))


if __name__ == "__main__":
    main()
