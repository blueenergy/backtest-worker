"""daily_sma_cross must be runnable end to end by the worker.

The 2026-11-02 lab failure ("Unknown strategy: daily_sma_cross") was a
registry gap: the UI offered the key but the worker's STRATEGY_MAP had no
entry, so every task failed before any data was loaded. These tests pin the
key, its preset and a real backtrader run through SimpleBacktestRunner.
"""
import pandas as pd
from unittest.mock import Mock

from quant_strategies.strategies import STRATEGY_MAP
from quant_strategies.strategy_params.factory import create_strategy_with_params

from worker.simple_backtest_runner import SimpleBacktestRunner

N_BARS = 120


def _prices():
    """Flat, then up, then down: a golden cross and later a death cross.

    A monotonic rise is not enough: the fast average is already above the
    slow one on the first bar where the slow window exists, so no cross is
    ever observed.
    """
    prices = [100.0] * 30
    price = prices[-1]
    for _ in range(40):
        price += 1.0
        prices.append(price)
    for _ in range(50):
        price -= 1.0
        prices.append(price)
    return prices


def _mock_bars(runner):
    """Install a loader that returns an OHLCV frame with two crossings."""
    prices = _prices()
    dates = pd.date_range(start='2023-01-01', periods=len(prices), freq='D')
    frame = pd.DataFrame(
        {
            'open': prices,
            'high': [p + 2 for p in prices],
            'low': [p - 2 for p in prices],
            'close': prices,
            'volume': [1000 + i * 100 for i in range(len(prices))],
        },
        index=dates,
    )
    frame["pre_close"] = frame["close"].shift(1).fillna(frame["close"])
    frame["adj_factor"] = 1.0
    frame.attrs = {
        "adj_degraded": False,
        "adj_coverage": 1.0,
        "adj_bfilled": False,
    }
    runner.adj_loader = Mock()
    runner.adj_loader.load_adjusted_ohlc.return_value = frame


def test_daily_sma_cross_is_in_strategy_map():
    """The worker whitelist must carry the key the UI offers."""
    assert "daily_sma_cross" in STRATEGY_MAP


def test_daily_sma_default_preset_resolves_to_the_shell():
    strategy_class, params = create_strategy_with_params("daily_sma_default")

    assert strategy_class is STRATEGY_MAP["daily_sma_cross"]
    assert params["fast_period"] == 10
    assert params["slow_period"] == 30


def test_runner_runs_daily_sma_cross_with_preset_and_overrides():
    runner = SimpleBacktestRunner()
    _mock_bars(runner)

    results = runner.run_backtest(
        symbol='TEST.SZ',
        strategy_class=STRATEGY_MAP['daily_sma_cross'],
        strategy_params={
            'fast_period': 5,
            'slow_period': 20,
            'position_pct': 0.5,
            'account_capital': 100000.0,
        },
        start_date='20230101',
        end_date='20231031',
        initial_cash=100000,
        preset_name='daily_sma_default',
    )

    assert 'metrics' in results
    assert 'trades' in results
    assert 'equity_curve' in results
    # The path crosses once in each direction, so the round trip closes.
    assert [t['action'].lower() for t in results['trades']] == ['buy', 'sell']
    assert results['trades'][0]['quantity'] == results['trades'][1]['quantity']
