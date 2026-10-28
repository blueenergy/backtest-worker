"""Index bull/bear gate for Strategy Lab backtests.

The labels come from ``stock_data_access.regime`` — the exact implementation
portfolio research uses for its non-bull-cash overlay. This module only turns
those labels into a backtest gate:

* ``bull``      — the strategy runs unchanged.
* ``bear``/``uncertain`` — buys and target-increases are dropped; a held
  position is closed at the next open. Sells and closes always pass.

Labels are as-of the bar close. With backtrader's default next-open execution a
decision made on day D fills at D+1's open, so the close used to label D is not
look-ahead. The Strategy Lab path (``cheat_on_open=False``) uses
``label_lag_bars=0``; a cheat-on-open run must pass ``label_lag_bars=1``.
"""

from __future__ import annotations

import bisect
import logging
import math
from typing import Any, Dict, Optional

import pandas as pd

from stock_data_access.regime import (
    DEFAULT_REGIME_RULE_ID,
    label_index_regime,
    list_regime_rule_presets,
    padded_index_start,
)

log = logging.getLogger(__name__)

# A regime label is path-dependent; require a real warm-up rather than silently
# labelling a short window "uncertain" and blocking every buy.
MIN_LABEL_BARS = 120


class RegimeDataError(ValueError):
    """Raised when a requested regime filter cannot be evaluated."""


class RegimeFilter:
    """Sorted date -> bull/bear/uncertain lookup with an as-of query."""

    def __init__(self, labels: pd.DataFrame, *, index_symbol: str, rule: str):
        if labels is None or labels.empty:
            raise RegimeDataError(f"regime labels empty for {index_symbol}")
        missing = {"trade_date", "label"} - set(labels.columns)
        if missing:
            raise RegimeDataError(
                f"regime labels for {index_symbol} missing columns: {sorted(missing)}"
            )
        frame = labels[["trade_date", "label"]].copy()
        frame["trade_date"] = frame["trade_date"].astype(str)
        frame = frame.drop_duplicates("trade_date").sort_values("trade_date")
        self.index_symbol = index_symbol
        self.rule = rule
        self.dates = frame["trade_date"].tolist()
        self.labels = frame["label"].astype(str).tolist()
        self.distribution: Dict[str, int] = {
            key: self.labels.count(key) for key in ("bull", "bear", "uncertain")
        }

    def label_on(self, trade_date: str) -> str:
        """Last label visible on or before ``trade_date`` (YYYYMMDD)."""
        idx = bisect.bisect_right(self.dates, str(trade_date)) - 1
        if idx < 0:
            return "uncertain"
        return self.labels[idx]

    def is_bull(self, trade_date: str) -> bool:
        return self.label_on(trade_date) == "bull"

    def __len__(self) -> int:
        return len(self.dates)


def load_regime_filter(
    *,
    index_symbol: str,
    start_date: str,
    end_date: str,
    rule: Optional[str] = None,
    db: Any = None,
    label_lag_bars: int = 0,
) -> RegimeFilter:
    """Load index prices, label them, and validate the requested window.

    ``db`` is injectable for tests; production uses the shared
    ``stock_data_access.mongo_context.get_db`` handle (``quant_data``).
    """
    symbol = str(index_symbol or "").strip()
    if not symbol:
        raise RegimeDataError("regime filter requires an index symbol")
    rule_id = str(rule or "").strip() or DEFAULT_REGIME_RULE_ID
    if rule_id not in list_regime_rule_presets():
        raise RegimeDataError(
            f"unsupported regime rule {rule_id!r}; "
            f"use one of {', '.join(list_regime_rule_presets())}"
        )
    lag = int(label_lag_bars)
    if lag < 0:
        raise RegimeDataError(f"label_lag_bars must be >= 0, got {label_lag_bars!r}")

    padded_start = padded_index_start(start_date)
    if db is None:
        from stock_data_access.mongo_context import get_db

        db = get_db()

    rows = list(
        db["index_prices"]
        .find(
            {
                "ts_code": symbol,
                "trade_date": {"$gte": padded_start, "$lte": str(end_date)},
            },
            {
                "_id": 0,
                "trade_date": 1,
                "close": 1,
                "high": 1,
                "low": 1,
                "vol": 1,
                "volume": 1,
            },
        )
        .sort("trade_date", 1)
    )
    if not rows:
        raise RegimeDataError(
            f"regime filter requires index prices for {symbol} "
            f"from {padded_start} to {end_date}"
        )

    labels = label_index_regime(rows, regime_rule=rule_id)
    regime = RegimeFilter(labels, index_symbol=symbol, rule=rule_id)
    if len(regime) < MIN_LABEL_BARS:
        raise RegimeDataError(
            f"regime labels for {symbol} have only {len(regime)} bars "
            f"(need {MIN_LABEL_BARS}) from {padded_start} to {end_date}"
        )
    start_text = str(start_date).replace("-", "")[:8]
    if regime.dates[0] > start_text:
        raise RegimeDataError(
            f"regime labels for {symbol} start at {regime.dates[0]}, "
            f"after the backtest start {start_text}; extend the warm-up"
        )
    regime.label_lag_bars = lag
    return regime


def _position_value(strategy, data) -> float:
    try:
        price = float(data.close[0])
    except (IndexError, TypeError, ValueError):
        return 0.0
    if not math.isfinite(price) or price <= 0:
        return 0.0
    try:
        size = abs(int(strategy.getposition(data).size))
    except (AttributeError, TypeError, ValueError):
        return 0.0
    return size * price


def _pending_orders(strategy):
    return list(getattr(strategy, "_orderspending", []) or [])


def wrap_strategy_with_regime(
    strategy_class: type,
    regime: RegimeFilter,
    *,
    label_lag_bars: int = 0,
):
    """Return a subclass that blocks entries while the index is not bull."""
    lag = int(label_lag_bars)

    class RegimeGatedStrategy(strategy_class):
        def __init__(self):
            super().__init__()
            self._regime_filter = regime
            self._regime_lag = lag
            self._regime_label = "uncertain"
            self._regime_date: Optional[str] = None
            self._regime_exit_pending = None

        def _refresh_regime(self) -> None:
            data = self.datas[0]
            offset = -self._regime_lag if self._regime_lag else 0
            try:
                day = data.datetime.date(offset)
            except (IndexError, TypeError, ValueError):
                day = data.datetime.date(0)
            text = day.strftime("%Y%m%d")
            if text != self._regime_date:
                self._regime_date = text
                self._regime_label = self._regime_filter.label_on(text)

        def _regime_blocked(self) -> bool:
            return self._regime_label != "bull"

        def _close_for_regime(self) -> None:
            position = self.getposition(self.datas[0])
            if int(position.size) <= 0:
                return
            pending = _pending_orders(self)
            # A buy queued before the flip must not fill on the next open.
            for order in pending:
                if order.isbuy() and order.alive():
                    self.cancel(order)
            # The strategy may already be exiting on its own; don't stack a
            # second full-size sell that could flip the account short.
            if any((not order.isbuy()) and order.alive() for order in pending):
                return
            self._regime_exit_pending = self.close()

        def next(self):
            self._refresh_regime()
            super().next()
            if self._regime_blocked():
                self._close_for_regime()

        def buy(self, *args, **kwargs):
            self._refresh_regime()
            if self._regime_blocked():
                return None
            return super().buy(*args, **kwargs)

        def order_target_size(self, data, target):
            self._refresh_regime()
            if self._regime_blocked():
                current = abs(int(self.getposition(data).size))
                if abs(target) > current:
                    return None
            return super().order_target_size(data, target)

        def order_target_value(self, data, value):
            self._refresh_regime()
            if self._regime_blocked() and float(value) > _position_value(self, data):
                return None
            return super().order_target_value(data, value)

        def order_target_percent(self, data, target):
            self._refresh_regime()
            if self._regime_blocked():
                account_value = float(self.broker.getvalue()) or 1.0
                if float(target) * account_value > _position_value(self, data):
                    return None
            return super().order_target_percent(data, target)

        def notify_order(self, order):
            if order is self._regime_exit_pending and not order.alive():
                self._regime_exit_pending = None
            super().notify_order(order)

    return RegimeGatedStrategy


__all__ = [
    "MIN_LABEL_BARS",
    "RegimeDataError",
    "RegimeFilter",
    "load_regime_filter",
    "wrap_strategy_with_regime",
]
