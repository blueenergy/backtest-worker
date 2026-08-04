"""A-share price limit enforcement for Backtrader backtests.

Pre-computes limit-up / limit-down flags from ``pre_close`` and board type,
then blocks buys on limit-up days and sells on limit-down days.
"""
from __future__ import annotations

import re
from typing import Optional

import numpy as np
import backtrader as bt
from backtrader.brokers import BackBroker
from backtrader.order import Order


def _limit_pct(symbol: str, name: str = "") -> float:
    """Return daily price limit fraction for an A-share symbol."""
    label = f"{symbol} {name}".upper()
    if "ST" in label:
        return 0.05
    if symbol.endswith(".BJ"):
        return 0.30
    # ChiNext / STAR
    code = symbol.split(".", 1)[0]
    if re.match(r"^30\d{4}$", code) or re.match(r"^68\d{4}$", code):
        return 0.20
    return 0.10


def annotate_limit_flags(df, symbol: str, name: str = ""):
    """Add ``limit_up`` and ``limit_down`` boolean columns to a price frame."""
    import pandas as pd

    out = df.copy()
    pct = _limit_pct(symbol, name=name)
    if "pre_close" in out.columns:
        pre = pd.to_numeric(out["pre_close"], errors="coerce")
    else:
        pre = pd.Series(np.nan, index=out.index)
    if not isinstance(pre, pd.Series) or pre.isna().all():
        pre = pd.to_numeric(out["close"], errors="coerce").shift(1)
    limit_up_price = pre * (1.0 + pct)
    limit_down_price = pre * (1.0 - pct)
    close = pd.to_numeric(out["close"], errors="coerce")
    out["limit_up"] = close >= (limit_up_price * 0.998)
    out["limit_down"] = close <= (limit_down_price * 1.002)
    return out


class AShareBroker(BackBroker):
    """BackBroker that enforces A-share daily price limits."""

    def _try_exec(self, order):
        data = order.data
        if getattr(data, "limit_up", None) is not None:
            try:
                if order.isbuy() and bool(data.limit_up[0]):
                    order.cancel()
                    return
                if not order.isbuy() and bool(data.limit_down[0]):
                    order.cancel()
                    return
            except (IndexError, TypeError, ValueError):
                pass
        super()._try_exec(order)


class LimitFlagPandasData(bt.feeds.PandasData):
    """PandasData feed carrying optional limit-up/down lines."""

    lines = ("adj_factor", "limit_up", "limit_down")
    params = (
        ("adj_factor", -1),
        ("limit_up", -1),
        ("limit_down", -1),
    )


def make_ashare_feed(df, symbol: str, stock_name: str = ""):
    """Build a NamedPandasData feed with limit flags and optional adj_factor."""
    import pandas as pd

    frame = annotate_limit_flags(df, symbol, name=stock_name)
    data_df = frame.copy()
    dt_index = pd.to_datetime(data_df.index)
    data_df = data_df.set_index(dt_index).sort_index()

    feed_kwargs = {
        "dataname": data_df,
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "openinterest": -1,
    }
    if "adj_factor" in data_df.columns:
        feed_kwargs["adj_factor"] = "adj_factor"
    if "limit_up" in data_df.columns:
        feed_kwargs["limit_up"] = "limit_up"
    if "limit_down" in data_df.columns:
        feed_kwargs["limit_down"] = "limit_down"

    data = LimitFlagPandasData(**feed_kwargs)
    data.symbol = symbol
    data._name = symbol
    data.stock_name = stock_name or symbol
    return data


__all__ = [
    "AShareBroker",
    "LimitFlagPandasData",
    "annotate_limit_flags",
    "make_ashare_feed",
    "_limit_pct",
]
