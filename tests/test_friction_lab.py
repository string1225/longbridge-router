from datetime import date, timedelta

import pytest

from research import wave_lab
from research.friction_lab import FrictionPortfolio, run_scenario


def sample(prices):
    return [
        wave_lab.Bar(date(2025, 11, 3) + timedelta(days=i), p, p, p, p)
        for i, p in enumerate(prices)
    ]


def test_fractional_zero_minimum_reproduces_existing_engine_for_all_variants():
    bars = sample([100 * (1.06 if i % 2 else 0.96) ** (i % 15) for i in range(65)])
    for variant in wave_lab.VARIANTS:
        expected = wave_lab.simulate(bars, variant, fee_rate=0.0025, capital=10000)
        actual = run_scenario(
            bars, variant, capital=10000, fee_rate=0.0025, lot_size=0, minimum_fee=0
        )
        assert actual["metrics"] == pytest.approx(expected["metrics"])


def test_small_order_pays_minimum_and_cannot_borrow():
    p = FrictionPortfolio(1000, 0, 0.001, [], lot_size=1, minimum_fee=5)
    assert p.execute(
        sample([100])[0],
        {"target_weight": 1, "signal_date": None, "reason": "initial"},
        bounded=False,
    )
    assert p.shares == 9
    assert p.cash == 95
    assert p.trades[0]["fee"] == 5


def test_lot_rounding_can_prevent_initial_allocation_without_claiming_strategy_profit():
    result = run_scenario(
        sample([600, 630, 570]),
        "grid_5",
        capital=10000,
        fee_rate=0.0025,
        lot_size=100,
        minimum_fee=5,
    )
    assert result["metrics"]["trade_count"] == 0
    assert result["initial_fill"] is False
    assert result["metrics"]["return"] == 0
    assert result["metrics"]["mean_exposure"] == 0
    assert result["skip_counts"]["lot_or_budget"] > 0


def test_minimum_fee_and_board_lots_respect_postfee_position_bounds():
    p = FrictionPortfolio(10000, 0, 0.001, [], lot_size=10, minimum_fee=20)
    bar = sample([30])[0]
    assert p.execute(
        bar, {"target_weight": 0.5, "signal_date": None, "reason": "initial"}, bounded=False
    )
    assert p.execute(
        bar,
        {"side": "buy", "notional": 1e6, "signal_date": "2025-11-03", "reason": "test"},
        bounded=True,
    )
    assert p.trades[-1]["stock_exposure_after"] <= 0.8 + 1e-12
    assert p.execute(
        bar,
        {"side": "sell", "notional": 1e6, "signal_date": "2025-11-03", "reason": "test"},
        bounded=True,
    )
    assert p.trades[-1]["stock_exposure_after"] >= 0.2 - 1e-12
    assert p.cash >= 0 and p.shares >= 0
    assert all(t["shares"] % 10 == 0 for t in p.trades)


def test_proportional_fees_dominate_minimum_for_large_orders():
    p = FrictionPortfolio(100000, 0, 0.0025, [], lot_size=0, minimum_fee=5)
    assert p.execute(
        sample([100])[0],
        {"target_weight": 0.5, "signal_date": None, "reason": "initial"},
        bounded=False,
    )
    trade = p.trades[0]
    assert trade["fee"] == pytest.approx(trade["notional"] * 0.0025)
    assert trade["stock_exposure_after"] == pytest.approx(0.5)


@pytest.mark.parametrize("lot,minimum", [(-1, 0), (1, -1), (1, float("nan"))])
def test_invalid_friction_is_rejected(lot, minimum):
    with pytest.raises(ValueError):
        FrictionPortfolio(1000, 0, 0.001, [], lot_size=lot, minimum_fee=minimum)


def test_failed_lot_breakout_does_not_start_trailing_exit_state():
    result = run_scenario(
        sample([600] * 20 + [660, 700, 600, 500]),
        "trend_20_5",
        capital=10000,
        fee_rate=0.0025,
        lot_size=100,
        minimum_fee=5,
    )
    assert result["metrics"]["trade_count"] == 0
    assert not any(s["reason"] == "trailing_close_5_stop" for s in result["signals"])


def test_failed_trailing_exit_retries_while_position_is_still_held():
    class RejectExit(wave_lab._Portfolio):
        def execute(self, bar, order, bounded):
            if order["reason"] == "trailing_close_5_stop":
                return False
            return super().execute(bar, order, bounded)

    result = wave_lab.simulate(
        sample([100] * 20 + [110, 120, 110, 100, 95]), "trend_20_5", portfolio_factory=RejectExit
    )
    assert sum(s["reason"] == "trailing_close_5_stop" for s in result["signals"]) >= 2
