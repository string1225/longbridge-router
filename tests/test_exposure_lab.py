from datetime import date, timedelta

import pytest

from research import fingerprint, wave_lab
from research.exposure_lab import build_exposure_report, calibrate_weight, constant_weight


def bars(closes, start=date(2025, 11, 3)):
    return [wave_lab.Bar(start + timedelta(days=i), p, p, p, p) for i, p in enumerate(closes)]


def test_constant_half_reproduces_existing_monthly_baseline():
    sample = bars([100 * 1.01**i for i in range(65)])
    expected = wave_lab.simulate(sample, "monthly_50", fee_rate=0.0025)
    actual = constant_weight(sample, 0.5, fee_rate=0.0025)
    assert actual["metrics"] == expected["metrics"]
    assert [t["notional"] for t in actual["trades"]] == [t["notional"] for t in expected["trades"]]


def test_posthoc_control_matches_realized_exposure_and_labels_lookahead():
    sample = bars([100 * (1.01 if i % 2 else 0.99) ** i for i in range(75)])
    actual = calibrate_weight(sample, 0.36, fee_rate=0.001)
    assert actual["uses_test_period_information"] is True
    assert abs(actual["exposure_error"]) < 0.0001
    assert actual["simulation"]["metrics"]["mean_exposure"] == pytest.approx(0.36, abs=0.0001)


@pytest.mark.parametrize("weight", [-0.1, 1.01, float("nan")])
def test_invalid_weight_is_rejected(weight):
    with pytest.raises(ValueError):
        constant_weight(bars([100, 101]), weight, fee_rate=0.001)


def fixture():
    training = bars(
        [100 * (1.04 if i % 2 else 0.96) ** i for i in range(145)], start=date(2025, 1, 1)
    )
    test = bars([100 + i for i in range(65)])
    rows = [
        {
            "date": b.date.isoformat(),
            "open": str(b.open),
            "close": str(b.close),
            "high": str(b.high),
            "low": str(b.low),
        }
        for b in training + test
    ]
    dataset = {"history": {s: {"data": {"candlesticks": rows}} for s in ("A.US", "AH.HK", "B.US")}}
    universe = {
        "volatility_candidates": [
            {"symbol": "A.US", "issuer_group": "A"},
            {"symbol": "AH.HK", "issuer_group": "A"},
            {"symbol": "B.US"},
        ]
    }
    return dataset, universe, wave_lab.build_report(dataset, universe)


def test_training_control_weight_ignores_later_price_revisions_and_groups_issuers():
    dataset, universe, wave = fixture()
    first = build_exposure_report(dataset, universe, wave)
    for raw in dataset["history"].values():
        for row in raw["data"]["candlesticks"]:
            if row["date"] >= "2025-11-01":
                for field in ("open", "close", "high", "low"):
                    row[field] = str(float(row[field]) * 2)
    second = build_exposure_report(dataset, universe, wave_lab.build_report(dataset, universe))
    for symbol in first["stocks"]:
        for variant in first["stocks"][symbol]:
            assert (
                first["stocks"][symbol][variant]["training_control"]["target_weight"]
                == (second["stocks"][symbol][variant]["training_control"]["target_weight"])
            )
    assert first["aggregate"]["issuer_count"] == 2
    assert first["aggregate"]["listing_count"] == 3
    assert second["provenance"]["history_fingerprint"] == fingerprint(dataset["history"])
    assert first["provenance"]["history_fingerprint"] != second["provenance"]["history_fingerprint"]


def test_exposure_report_rejects_stale_simulation():
    dataset, universe, wave = fixture()
    dataset["history"].pop("A.US")
    with pytest.raises(ValueError, match="provenance"):
        build_exposure_report(dataset, universe, wave)
