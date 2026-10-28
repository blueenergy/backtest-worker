"""Tests for the Strategy Lab bull/bear gate."""

from datetime import datetime, timedelta

import backtrader as bt
import pandas as pd
import pytest

from worker.regime_filter import (
    RegimeDataError,
    RegimeFilter,
    load_regime_filter,
    wrap_strategy_with_regime,
)


def _labels(start: str, days: int, *, bull_until: int, bear_until: int) -> pd.DataFrame:
    begin = datetime.strptime(start, "%Y%m%d")
    rows = []
    for idx in range(days):
        if idx < bull_until:
            label = "bull"
        elif idx < bear_until:
            label = "bear"
        else:
            label = "bull"
        rows.append(
            {
                "trade_date": (begin + timedelta(days=idx)).strftime("%Y%m%d"),
                "label": label,
            }
        )
    return pd.DataFrame(rows)


def test_label_on_uses_last_visible_label():
    regime = RegimeFilter(
        _labels("20240101", 10, bull_until=5, bear_until=8),
        index_symbol="000300.SH",
        rule="k_slow_anchor",
    )
    assert regime.label_on("20240101") == "bull"
    assert regime.label_on("20240105") == "bull"
    assert regime.label_on("20240106") == "bear"
    assert regime.label_on("20240109") == "bull"
    assert regime.label_on("20231231") == "uncertain"


def test_unknown_regime_rule_is_rejected():
    with pytest.raises(RegimeDataError, match="unsupported regime rule"):
        load_regime_filter(
            index_symbol="000300.SH",
            start_date="20240101",
            end_date="20241231",
            rule="not_a_rule",
            db=object(),
        )


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction):
        self.rows = sorted(self.rows, key=lambda row: row[key], reverse=direction < 0)
        return self

    def __iter__(self):
        return iter(self.rows)


class _Collection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query, projection):
        lower = query["trade_date"]["$gte"]
        upper = query["trade_date"]["$lte"]
        return _Cursor(
            [
                row
                for row in self.rows
                if row["ts_code"] == query["ts_code"]
                and lower <= row["trade_date"] <= upper
            ]
        )


class _DB(dict):
    pass


def _index_rows(start: str, days: int) -> list:
    begin = datetime.strptime(start, "%Y%m%d")
    rows = []
    for idx in range(days):
        rows.append(
            {
                "ts_code": "000300.SH",
                "trade_date": (begin + timedelta(days=idx)).strftime("%Y%m%d"),
                "close": 100.0 + idx * 0.05,
                "high": 101.0 + idx * 0.05,
                "low": 99.0 + idx * 0.05,
                "vol": 1000.0 + idx,
            }
        )
    return rows


def test_load_regime_filter_reads_index_prices():
    db = _DB(index_prices=_Collection(_index_rows("20230101", 200)))
    regime = load_regime_filter(
        index_symbol="000300.SH",
        start_date="20230701",
        end_date="20230719",
        db=db,
    )
    assert len(regime) >= 120
    assert regime.index_symbol == "000300.SH"
    assert regime.rule == "k_slow_anchor"


def test_load_regime_filter_fails_when_index_missing():
    db = _DB(index_prices=_Collection([]))
    with pytest.raises(RegimeDataError, match="requires index prices"):
        load_regime_filter(
            index_symbol="000300.SH",
            start_date="20230701",
            end_date="20230719",
            db=db,
        )


class _BuyEveryBar(bt.Strategy):
    def __init__(self):
        self.fills = []
        self.buy_orders = []

    def next(self):
        if not self.position:
            order = self.buy(size=100)
            self.buy_orders.append(
                (self.data.datetime.date(0).strftime("%Y%m%d"), order)
            )

    def notify_order(self, order):
        if order.status == order.Completed:
            self.fills.append(
                (order.data.datetime.date(0).strftime("%Y%m%d"), "buy" if order.isbuy() else "sell")
            )


def _price_frame(start: str, days: int) -> pd.DataFrame:
    begin = datetime.strptime(start, "%Y%m%d")
    dates = [begin + timedelta(days=idx) for idx in range(days)]
    return pd.DataFrame(
        {
            "open": [10.0] * days,
            "high": [10.1] * days,
            "low": [9.9] * days,
            "close": [10.0] * days,
            "volume": [10000] * days,
        },
        index=pd.to_datetime(dates),
    )


def test_gate_works_with_backtest_strategy_base():
    from quant_strategies.strategies.base import BacktestStrategy

    class _BaseBuyEveryBar(BacktestStrategy):
        def next(self):
            super().next()
            if self.get_strategy_owned_qty() == 0:
                self.buy(size=100)

    labels = _labels("20240101", 120, bull_until=50, bear_until=80)
    regime = RegimeFilter(labels, index_symbol="000300.SH", rule="k_slow_anchor")
    wrapped = wrap_strategy_with_regime(_BaseBuyEveryBar, regime)

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0)
    cerebro.addstrategy(wrapped)
    cerebro.adddata(bt.feeds.PandasData(dataname=_price_frame("20240101", 120)))
    strategy = cerebro.run()[0]

    label_by_date = dict(zip(labels["trade_date"], labels["label"]))
    assert strategy.trades_log, "bull entries should still be recorded"
    assert any(label_by_date[t["datetime"].strftime("%Y%m%d")] == "bull" for t in strategy.trades_log)


def test_buys_are_blocked_and_position_is_closed_outside_bull():
    labels = _labels("20240101", 120, bull_until=50, bear_until=80)
    regime = RegimeFilter(labels, index_symbol="000300.SH", rule="k_slow_anchor")
    wrapped = wrap_strategy_with_regime(_BuyEveryBar, regime)

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0)
    cerebro.addstrategy(wrapped)
    frame = _price_frame("20240101", 120)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    strategies = cerebro.run()
    fills = strategies[0].fills

    label_by_date = dict(zip(labels["trade_date"], labels["label"]))
    strategy = strategies[0]
    completed_buys = [date for date, action in strategy.fills if action == "buy"]
    sell_dates = [date for date, action in strategy.fills if action == "sell"]

    assert completed_buys, "the bull windows should still allow entries"
    # A buy submitted on a non-bull bar must have been canceled, not filled.
    for date, order in strategy.buy_orders:
        if label_by_date[date] != "bull":
            assert order is None or order.status != order.Completed, (date, order)
    assert sell_dates, "the first bear bar should force an exit"
    assert label_by_date[sell_dates[0]] == "bear"
