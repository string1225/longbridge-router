"""Compile an offline daily research report; never read credentials or place orders."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from research import fingerprint
from research.collect import market_of, save_json
from research.wave_lab import normalize_bars


def _event_fingerprints(evidence):
    return {event["id"]: fingerprint(event) for event in evidence.get("events", [])}


def build_daily_report(
    dataset, wave, evidence, universe, *, report_date, previous=None, comparisons=None
):
    """Keep measured price results separate from incomplete dividend evidence.

    Fingerprints distinguish new observations/revisions from a repeated download.
    All performance fields retain the engine's decimal units and cost assumptions.
    """
    expected_provenance = {
        "history_fingerprint": fingerprint(dataset.get("history", {})),
        "universe_fingerprint": fingerprint(universe),
    }
    artifacts = [wave, *(comparisons or {}).values()]
    for artifact in artifacts:
        if artifact.get("provenance") != expected_provenance:
            raise ValueError("Missing or different simulation provenance; rerun it first")
    symbols = sorted(
        {
            item["symbol"]
            for role in ("dividend_candidates", "volatility_candidates", "benchmarks")
            for item in universe.get(role, [])
        }
    )
    histories, markets, missing, omitted = {}, {}, [], {}
    for symbol in symbols:
        raw = dataset.get("history", {}).get(symbol)
        bars = normalize_bars(raw, symbol=symbol)
        raw_count = len((raw or {}).get("data", {}).get("candlesticks", []))
        if raw_count > len(bars):
            omitted[symbol] = raw_count - len(bars)
        if not bars:
            missing.append(symbol)
            continue
        histories[symbol] = {
            "count": len(bars),
            "first_session": bars[0].date.isoformat(),
            "last_session": bars[-1].date.isoformat(),
            "fingerprint": fingerprint(raw),
        }
        market = markets.setdefault(
            market_of(symbol),
            {
                "symbol_count": 0,
                "first_session": bars[0].date.isoformat(),
                "last_session": bars[-1].date.isoformat(),
                "earliest_symbol_last_session": bars[-1].date.isoformat(),
            },
        )
        market["symbol_count"] += 1
        market["first_session"] = min(market["first_session"], bars[0].date.isoformat())
        market["last_session"] = max(market["last_session"], bars[-1].date.isoformat())
        market["earliest_symbol_last_session"] = min(
            market["earliest_symbol_last_session"], bars[-1].date.isoformat()
        )

    candidates, events = evidence.get("candidates", []), evidence.get("events", [])
    sources = evidence.get("sources", {})
    event_fingerprints = _event_fingerprints(evidence)
    gaps = {
        field: sum(not event.get(field) for event in events)
        for field in ("announcement_date", "ex_date", "payment_date")
    }
    examples = {}
    for symbol in ("BABA.US", "TSLA.US", "NVDA.US", "AMD.US", "META.US", "COIN.US"):
        stock = wave.get("stocks", {}).get(symbol, {})
        if symbol not in wave["aggregate"]["eligible_symbols"]:
            continue
        examples[symbol] = {
            period: {name: value["metrics"] for name, value in result["strategies"].items()}
            for period, result in stock.get("periods", {}).items()
        }

    # A report never upgrades partial issuer evidence into simulated returns.
    dividend = {
        "evidence_as_of": evidence.get("as_of"),
        "candidate_count": len(candidates),
        "issuer_count": len({c.get("issuer_id", c["symbol"]) for c in candidates}),
        "source_count": len(sources),
        "source_ids": sorted(sources),
        "event_count": len(events),
        "event_fingerprints": event_fingerprints,
        "event_gaps": gaps,
        "data_status": evidence.get("data_status", {}),
        "backtest_status": "not_run",
        "candidate_reviews": [
            {
                k: c.get(k)
                for k in (
                    "symbol",
                    "issuer_id",
                    "ordinary_dps",
                    "quality_decision",
                    "confirmed_facts",
                    "inferences",
                    "missing",
                    "sources",
                )
            }
            for c in candidates
        ],
        "rule_proposals": evidence.get("rule_proposals", {}),
        "limitations": evidence.get("material_limitations", []),
    }

    changes = {
        "baseline_report": previous is None,
        "previous_date": None,
        "history_changed_symbols": [],
        "new_source_ids": [],
        "changed_event_ids": [],
        "wave_test_return_change": {},
    }
    if previous:
        changes["previous_date"] = previous["date"]
        old_histories = previous["data"]["histories"]
        changes["history_changed_symbols"] = sorted(
            symbol
            for symbol in set(histories) | set(old_histories)
            if histories.get(symbol, {}).get("fingerprint")
            != old_histories.get(symbol, {}).get("fingerprint")
        )
        changes["new_source_ids"] = sorted(set(sources) - set(previous["dividend"]["source_ids"]))
        old_events = previous["dividend"]["event_fingerprints"]
        changes["changed_event_ids"] = sorted(
            key
            for key in set(event_fingerprints) | set(old_events)
            if event_fingerprints.get(key) != old_events.get(key)
        )
        current_test = wave["aggregate"]["periods"].get("temporal_test", {}).get("variants", {})
        previous_test = previous["wave"]["periods"].get("temporal_test", {}).get("variants", {})
        for name, value in current_test.items():
            old = previous_test.get(name, {}).get("mean_return")
            new = value.get("mean_return")
            changes["wave_test_return_change"][name] = (
                new - old if old is not None and new is not None else None
            )

    return {
        "schema_version": 1,
        "date": report_date,
        "timezone": "Asia/Shanghai",
        "data": {
            "source": dataset.get("source"),
            "retrieved_at": dataset.get("retrieved_at"),
            "symbol_count": len(histories),
            "requested_symbol_count": len(symbols),
            "pool_sizes": {
                role: len(universe.get(role, []))
                for role in ("dividend_candidates", "volatility_candidates", "benchmarks")
            },
            "markets": markets,
            "histories": histories,
            "missing_symbols": missing,
            "errors": dataset.get("errors", []),
            "omitted_bars": omitted,
            "complete": not missing and not dataset.get("errors") and not omitted,
            "provenance_verified": all(
                a.get("provenance") == expected_provenance for a in artifacts
            ),
            "collection": dataset.get("collection", {}),
        },
        "dividend": dividend,
        "wave": {
            "eligible_count": wave["aggregate"]["eligible_wave_count"],
            "eligible_symbols": wave["aggregate"]["eligible_symbols"],
            "periods": wave["aggregate"]["periods"],
            "examples": examples,
            "methodology": wave.get("methodology", {}),
            "interpretation": "Per-stock cross-sectional statistics, not a pooled portfolio",
        },
        "comparisons": {
            label: {"methodology": value["methodology"], "periods": value["aggregate"]["periods"]}
            for label, value in (comparisons or {}).items()
        },
        "changes": changes,
        "next_experiments": [
            "补齐公告时点、除息与支付日期；先核对支付频次变化、削减和特别股息。",
            "按银行、能源、电信、REIT分别核对股息覆盖，建立基准与削减情景。",
            "在固定规则下加入整手、最低收费、税费与仓位可比基准，保留失败股票。",
            "记录2026-11-02起的新行情模拟，规则与候选池有变动时另记版本。",
        ],
        "limitations": [
            "手选存续股票含选择偏差；阿里ADR/港股、银行A/H不能当作独立发行人。",
            "历史测试已被查看，不能称为全新样本外结果；不挑最好阈值作为结论。",
            "前复权价格实验未独立重建现金股息总回报；股息池禁止据此前复权价算股息率。",
            "收益已扣模型费用，未计税、汇率、最低收费、整手、现金利息与流动性约束。",
            "平均回撤是各股回撤的均值，不是组合回撤；仓位差异影响收益比较。",
        ],
    }


def render_text(report):
    def pct(value):
        return "缺失" if value is None else f"{value:.2%}"

    data, dividend, wave = report["data"], report["dividend"], report["wave"]
    lines = [
        f"{report['date']} 阶段报告（北京时间）",
        f"样本：{data['symbol_count']}/{data['requested_symbol_count']}个代码；"
        f"接口错误{len(data['errors'])}项。",
    ]
    for market, detail in data["markets"].items():
        lines.append(
            f"{market}行情：{detail['first_session']}至{detail['last_session']}，"
            f"最早的个股末日为{detail['earliest_symbol_last_session']}。"
        )
    if data["omitted_bars"]:
        lines.append(f"OHLC无效或重复记录已剔除，需复核：{data['omitted_bars']}。")
    lines.append(
        f"股息池：{dividend['candidate_count']}个代码、{dividend['issuer_count']}个发行人，"
        f"{dividend['source_count']}份来源、{dividend['event_count']}条部分事件记录。"
        "股息策略尚未回测，分红安全性仍需核对。"
    )
    lines.append(f"事件缺口：{dividend['event_gaps']}。")
    lines.append(
        f"波动池：{wave['eligible_count']}只训练期合格候选。"
        "下列为逐股均值，不是组合收益；回撤为各股最大回撤的均值。"
    )
    for period, detail in wave["periods"].items():
        if detail.get("stock_count") == 0:
            lines.append(f"{period}：尚无已完成交易日数据。")
            continue
        lines.append(f"{period}（{detail.get('stock_count', wave['eligible_count'])}只）：")
        for name, metrics in detail["variants"].items():
            dd = metrics.get("mean_max_drawdown")
            lines.append(
                f"  {name}: 累计收益{pct(metrics.get('mean_return'))}，"
                f"年化均值{pct(metrics.get('mean_cagr'))}，"
                f"最大回撤均值{pct(abs(dd) if dd is not None else None)}，"
                f"交易次数均值{metrics.get('mean_trade_count')}，"
                f"平均仓位{pct(metrics.get('mean_mean_exposure'))}，"
                f"胜半仓{metrics.get('beat_half_hold_count')}/{metrics.get('stock_count')}。"
            )
    for label, comparison in report["comparisons"].items():
        values = comparison["periods"].get("temporal_test", {}).get("variants", {})
        lines.append(
            f"费用对照{label}："
            + "，".join(
                f"{name}={pct(value.get('mean_return'))}"
                for name, value in values.items()
                if name in ("half_hold", "grid_5", "reversal_5")
            )
        )
    if report["changes"]["baseline_report"]:
        lines.append("这是首份基线报告，不能把既有历史算作今天新增行情。")
    else:
        change = report["changes"]
        lines.append(
            f"相对{change['previous_date']}：历史变化{change['history_changed_symbols']}，"
            f"新增来源{change['new_source_ids']}，事件变化{change['changed_event_ids']}。"
        )
    lines.extend(report["limitations"])
    lines.append("下一步：" + "；".join(report["next_experiments"]))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--wave", type=Path, required=True)
    parser.add_argument(
        "--evidence", type=Path, default=Path(__file__).with_name("dividend_review.json")
    )
    parser.add_argument("--universe", type=Path, default=Path(__file__).with_name("universe.json"))
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--comparison", action="append", default=[], metavar="LABEL=PATH")
    parser.add_argument(
        "--date", default=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def read(path):
        return json.loads(path.read_text(encoding="utf-8-sig"))

    comparisons = {}
    for value in args.comparison:
        label, path = value.split("=", 1)
        comparisons[label] = read(Path(path))
    report = build_daily_report(
        read(args.dataset),
        read(args.wave),
        read(args.evidence),
        read(args.universe),
        report_date=args.date,
        previous=read(args.previous) if args.previous else None,
        comparisons=comparisons,
    )
    save_json(args.output, report)
    sys.stdout.reconfigure(encoding="utf-8")
    print(render_text(report))


if __name__ == "__main__":
    main()
