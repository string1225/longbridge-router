"""Offline nominal-price execution stress, separate from frozen forward paper rules."""

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from research import fingerprint
from research.collect import save_json
from research.wave_lab import TEST_END, TEST_START, VARIANTS, _Portfolio, normalize_bars, simulate


class FrictionPortfolio(_Portfolio):
    def __init__(self, *args, lot_size=0, minimum_fee=0):
        super().__init__(*args)
        if not math.isfinite(lot_size) or lot_size < 0 or int(lot_size) != lot_size:
            raise ValueError("lot_size must be zero (fractional) or a positive integer")
        if not math.isfinite(minimum_fee) or minimum_fee < 0:
            raise ValueError("minimum_fee must be finite and nonnegative")
        self.lot_size, self.minimum_fee = lot_size, minimum_fee
        self.skip_counts = Counter()

    def execute(self, bar, order, bounded):
        stock = self.shares * bar.open
        equity = self.cash + stock
        target = order.get("target_weight")
        if target is not None:
            difference = target * equity - stock
            if difference >= 0:
                delta = max(
                    0.0,
                    min(
                        difference / (1 + target * self.fee_rate),
                        difference - target * self.minimum_fee,
                    ),
                )
            else:
                delta = -max(
                    -difference / (1 - target * self.fee_rate),
                    -difference + target * self.minimum_fee,
                )
        else:
            delta = order["notional"] * (1 if order["side"] == "buy" else -1)
        if delta > 0:
            limit = min(self.cash / (1 + self.fee_rate), self.cash - self.minimum_fee)
            if bounded:
                room = 0.8 * equity - stock
                limit = min(
                    limit,
                    max(0.0, min(room / (1 + 0.8 * self.fee_rate), room - 0.8 * self.minimum_fee)),
                )
            delta = min(delta, max(0.0, limit))
        elif delta < 0:
            limit = stock
            if bounded:
                room = stock - 0.2 * equity
                limit = (
                    min(
                        limit,
                        max(
                            0.0,
                            max(room / (1 - 0.2 * self.fee_rate), room + 0.2 * self.minimum_fee),
                        ),
                    )
                    if room > 0
                    else 0.0
                )
            delta = -min(-delta, limit)
        if abs(delta) <= 1e-10:
            self.skip_counts["lot_or_budget"] += 1
            return False
        quantity = abs(delta) / bar.open
        if self.lot_size:
            quantity = math.floor(quantity / self.lot_size + 1e-12) * self.lot_size
        notional = quantity * bar.open
        if notional <= 1e-10:
            self.skip_counts["lot_or_budget"] += 1
            return False
        if notional < equity * 0.01 - 1e-8:
            self.skip_counts["dust"] += 1
            return False
        fee = max(notional * self.fee_rate, self.minimum_fee)
        signed = notional if delta > 0 else -notional
        next_cash = self.cash - signed - fee
        next_shares = self.shares + (quantity if delta > 0 else -quantity)
        if next_cash < -1e-8 or next_shares < -1e-8:
            self.skip_counts["fee_budget"] += 1
            return False
        self.cash, self.shares = max(0.0, next_cash), max(0.0, next_shares)
        after = self.cash + self.shares * bar.open
        self.trades.append(
            {
                "date": bar.date.isoformat(),
                "signal_date": order["signal_date"],
                "side": "buy" if delta > 0 else "sell",
                "price": bar.open,
                "notional": notional,
                "shares": quantity,
                "fee": fee,
                "reason": order["reason"],
                "equity_before": equity,
                "stock_exposure_after": self.shares * bar.open / after,
            }
        )
        return True


def run_scenario(bars, variant, *, capital, fee_rate, lot_size, minimum_fee, start=None, end=None):
    portfolios = []

    def factory(*args):
        portfolio = FrictionPortfolio(*args, lot_size=lot_size, minimum_fee=minimum_fee)
        portfolios.append(portfolio)
        return portfolio

    result = simulate(
        bars,
        variant,
        capital=capital,
        fee_rate=fee_rate,
        start=start,
        end=end,
        portfolio_factory=factory,
    )
    result["initial_fill"] = bool(result["trades"] and result["trades"][0]["reason"] == "initial")
    result["skip_counts"] = dict(portfolios[0].skip_counts) if portfolios else {}
    return result


def build_friction_report(raw, universe, selection_wave, *, capitals=(1000, 10000, 100000)):
    if raw.get("adjust_type") != 0:
        raise ValueError("Unadjusted history with adjust_type=0 required for nominal lot stress")
    if selection_wave.get("provenance", {}).get("universe_fingerprint") != fingerprint(universe):
        raise ValueError("Selection universe provenance mismatch")
    lots = {}
    for response in raw.get("static", {}).values():
        for item in (response or {}).get("data", {}).get("secu_static_info", []):
            lots[item["symbol"]] = int(item.get("lot_size", 0))
    stocks, omitted = {}, {}
    models = ("fractional", "fractional_minimum", "lots", "lots_minimum")
    for symbol in selection_wave["aggregate"]["eligible_symbols"]:
        stock = selection_wave["stocks"][symbol]
        bars = normalize_bars(raw.get("history", {}).get(symbol), symbol=symbol)
        observed = [bar for bar in bars if TEST_START <= bar.date <= TEST_END]
        if not observed or lots.get(symbol, 0) < 1:
            omitted[symbol] = "missing_history_or_current_lot"
            continue
        minimum = 5.0 if stock["market"] == "HK" else 1.0
        rows = {}
        for capital in capitals:
            rows[str(capital)] = {}
            for model in models:
                rows[str(capital)][model] = {}
                for variant in VARIANTS:
                    result = run_scenario(
                        bars,
                        variant,
                        capital=capital,
                        fee_rate=stock["fee_rate"],
                        lot_size=lots[symbol] if model.startswith("lots") else 0,
                        minimum_fee=minimum if model.endswith("minimum") else 0,
                        start=TEST_START,
                        end=TEST_END,
                    )
                    rows[str(capital)][model][variant] = {
                        "metrics": result["metrics"],
                        "initial_fill": result["initial_fill"],
                        "skip_counts": result["skip_counts"],
                    }
        stocks[symbol] = {
            "market": stock["market"],
            "currency": stock["currency"],
            "current_lot_size": lots[symbol],
            "lot_snapshot": raw["retrieved_at"],
            "test_start": observed[0].date.isoformat(),
            "test_end": observed[-1].date.isoformat(),
            "initial_price": observed[0].open,
            "one_lot_initial_notional": observed[0].open * lots[symbol],
            "assumed_minimum": minimum,
            "results": rows,
        }
    aggregate = {}
    for market in ("HK", "US"):
        members = [s for s in stocks if stocks[s]["market"] == market]
        aggregate[market] = {"listing_count": len(members), "capitals": {}}
        for capital in capitals:
            models_result = {}
            for model in models:
                models_result[model] = {}
                for variant in VARIANTS:
                    rows = [stocks[s]["results"][str(capital)][model][variant] for s in members]
                    metrics = [row["metrics"] for row in rows]
                    models_result[model][variant] = {
                        **{
                            "mean_" + field: statistics.fmean(m[field] for m in metrics)
                            if metrics
                            else None
                            for field in (
                                "return",
                                "max_drawdown",
                                "mean_exposure",
                                "trade_count",
                                "cost_fraction_initial_equity",
                            )
                        },
                        "initial_fill_count": sum(row["initial_fill"] for row in rows),
                        "zero_trade_count": sum(m["trade_count"] == 0 for m in metrics),
                    }
            aggregate[market]["capitals"][str(capital)] = models_result
    return {
        "schema_version": 1,
        "provenance": {
            "raw_history_fingerprint": fingerprint(raw.get("history", {})),
            "universe_fingerprint": fingerprint(universe),
            "selection_wave_provenance": selection_wave["provenance"],
        },
        "methodology": {
            "period": "2025-11-01..2026-10-30, inspected historical execution stress",
            "selection": "Original price-only training volatile cohort retained.",
            "price_basis": "Separate raw OHLC for all models/signals/controls. Differences from "
            "the older adjusted-price experiment cannot be attributed solely to fees.",
            "models": list(models),
            "capitals": list(capitals),
            "fees": "Same proportional assumptions as wave_lab; assumed minimum US USD1 / "
            "HK HKD5 per fill, fee=max(proportional,minimum). Not a broker tariff. "
            "Initial fee charged.",
            "lots": "Current lot snapshot held constant in history, not verified historical lots. "
            "US uses whole shares. Orders round down; zero trades indicate inability to follow "
            "the sizing rule, not alpha.",
            "capital": "Each symbol receives 1000/10000/100000 local units separately. "
            "HKD/USD are not comparable purchasing power or a pooled portfolio.",
            "limitations": [
                "No historical lot changes, splits/stock dividends/rights, cash dividends, taxes, "
                "FX, cash interest, order-book liquidity or actual tariff reconstructed.",
                "Raw ex-dividend gaps may trigger price signals; price return is not total return.",
                "Cash/20-80% bounds and1%-NAV dust retained. Close signals, next-open fills. "
                "Skipped orders change anchors/order paths; this is not a static fee deduction.",
                "Hand-selected survivors; Alibaba ADR/HK same issuer. Current lots use hindsight.",
                "Indicative stress only. Frozen forward rules and production gateway unchanged.",
            ],
        },
        "omitted_symbols": omitted,
        "stocks": stocks,
        "aggregate": aggregate,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("raw", "universe", "wave", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()

    def read(path):
        return json.loads(path.read_text(encoding="utf-8-sig"))

    report = build_friction_report(read(args.raw), read(args.universe), read(args.wave))
    save_json(args.output, report)
    print(
        json.dumps(
            {
                "stocks": len(report["stocks"]),
                "omitted": report["omitted_symbols"],
                "saved": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
