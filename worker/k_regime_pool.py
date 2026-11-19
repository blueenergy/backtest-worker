"""Independent strategy-pool type: K + volume + NATR timing.

This is not an overlay on hidden_dragon / turtle / single_yang. Buy and sell
both come from ``k_slow_anchor_with_vol_and_atr``. Universe is five Shenwan
L1 industries where the 2021-2026 scan's right tail concentrated.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from stock_data_access.regime import (
    CONFIRM_DAYS_DEFAULT,
    EXIT_CONFIRM_DAYS_DEFAULT,
    build_regime_cash_schedule,
)

STRATEGY_KEY = "k_regime"
DEFAULT_PRESET = "k_regime_default"
DEFAULT_REGIME_RULE = "k_slow_anchor_with_vol_and_atr"
DEFAULT_ADJUST = "qfq"
MIN_BARS = 250
TRADING_DAYS_PER_YEAR = 242

# SW2021 L1. Names are aliases for stock_info.sw_l1; codes are canonical.
K_REGIME_SW_L1_CODES: Tuple[str, ...] = (
    "801080.SI",  # 电子
    "801770.SI",  # 通信
    "801050.SI",  # 有色金属
    "801030.SI",  # 基础化工
    "801730.SI",  # 电力设备
)
K_REGIME_SW_L1_NAMES: Tuple[str, ...] = (
    "电子",
    "通信",
    "有色金属",
    "基础化工",
    "电力设备",
)

_ST_NAME_RE = re.compile(r"^[\*S]*ST", re.IGNORECASE)

DEFAULT_PARAMS: Dict[str, Any] = {
    "regime_rule": DEFAULT_REGIME_RULE,
    "confirm_days": CONFIRM_DAYS_DEFAULT,
    "exit_confirm_days": EXIT_CONFIRM_DAYS_DEFAULT,
    "fast_alpha": 0.967,
    "slow_alpha": 0.983,
    "industries": ",".join(K_REGIME_SW_L1_NAMES),
    "price_adjust": DEFAULT_ADJUST,
}


def is_st_name(name: Any) -> bool:
    return bool(_ST_NAME_RE.match(str(name or "").strip()))


def yyyymmdd(value: Any) -> str:
    text = str(value or "").strip().replace("-", "")[:8]
    if len(text) == 8 and text.isdigit():
        return text
    return ""


def shift_calendar(date_str: str, days: int) -> str:
    stamp = yyyymmdd(date_str)
    if not stamp:
        return ""
    return (datetime.strptime(stamp, "%Y%m%d") + timedelta(days=int(days))).strftime("%Y%m%d")


def _bar_date(row: Mapping[str, Any]) -> str:
    return yyyymmdd(row.get("trade_date") or row.get("date"))


def _bar_close(row: Mapping[str, Any]) -> Optional[float]:
    try:
        close = float(row.get("close"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(close) or close <= 0:
        return None
    return close


def trades_from_schedule(
    schedule: Sequence[Mapping[str, Any]],
    close_by_date: Mapping[str, float],
) -> List[Dict[str, Any]]:
    """Record BUY/SELL only on action flips. An initial invest is not a trade."""
    trades: List[Dict[str, Any]] = []
    prev: Optional[str] = None
    open_buy: Optional[Dict[str, Any]] = None
    for row in schedule:
        action = str(row.get("action") or "").strip().lower()
        date = yyyymmdd(row.get("score_date") or row.get("trade_date"))
        if not date or action not in {"invest", "cash"}:
            continue
        if prev is None:
            prev = action
            continue
        if action == prev:
            continue
        price = close_by_date.get(date)
        stamp = f"{date[:4]}-{date[4:6]}-{date[6:8]} 15:00:00"
        if action == "invest":
            open_buy = {
                "date": date,
                "datetime": stamp,
                "action": "BUY",
                "price": price,
                "quantity": 0,
                "pnl": 0.0,
                "cumulative_pnl": 0.0,
            }
            trades.append(open_buy)
        else:
            pnl = 0.0
            if open_buy and open_buy.get("price") and price:
                pnl = float(price) / float(open_buy["price"]) - 1.0
            sell = {
                "date": date,
                "datetime": stamp,
                "action": "SELL",
                "price": price,
                "quantity": 0,
                "pnl": pnl,
                "cumulative_pnl": 0.0,
            }
            trades.append(sell)
            open_buy = None
        prev = action

    cumulative = 0.0
    for trade in trades:
        if trade["action"] == "SELL":
            cumulative += float(trade.get("pnl") or 0.0)
        trade["cumulative_pnl"] = cumulative
    return trades


def _closed_round_win_rate(trades: Sequence[Mapping[str, Any]]) -> Tuple[float, int]:
    wins = 0
    closed = 0
    open_buy: Optional[Mapping[str, Any]] = None
    for trade in trades:
        action = str(trade.get("action") or "").upper()
        if action == "BUY":
            open_buy = trade
        elif action == "SELL" and open_buy is not None:
            closed += 1
            if float(trade.get("pnl") or 0.0) > 0:
                wins += 1
            open_buy = None
    if closed <= 0:
        return 0.0, 0
    return wins / closed, closed


def compute_path_metrics(
    rows: Sequence[Mapping[str, Any]],
    schedule: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
) -> Dict[str, float]:
    """Next-bar execution metrics, matching the research scan's shift(1) fills."""
    action_by_date = {yyyymmdd(item.get("score_date")): str(item.get("action") or "") for item in schedule if yyyymmdd(item.get("score_date"))}
    closes: List[float] = []
    dates: List[str] = []
    for row in rows:
        date = _bar_date(row)
        close = _bar_close(row)
        if not date or close is None:
            continue
        dates.append(date)
        closes.append(close)
    if len(closes) < 3:
        win_rate, n_closed = _closed_round_win_rate(trades)
        return {
            "hist_win_rate": win_rate,
            "hist_total_trades": float(n_closed),
            "hist_return": 0.0,
            "hist_sharpe_ratio": 0.0,
            "hist_max_drawdown": 0.0,
            "hist_calmar_ratio": 0.0,
        }

    daily: List[float] = [0.0]
    for idx in range(1, len(closes)):
        daily.append(closes[idx] / closes[idx - 1] - 1.0)

    # Position held on day i is yesterday's invest decision.
    strat: List[float] = []
    for idx, _date in enumerate(dates):
        prev_date = dates[idx - 1] if idx else ""
        held = action_by_date.get(prev_date) == "invest"
        strat.append(daily[idx] if held else 0.0)

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for ret in strat:
        equity *= 1.0 + ret
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = equity / peak - 1.0
            if dd < max_dd:
                max_dd = dd
    total_return = equity - 1.0

    if len(strat) >= 2:
        mean = sum(strat) / len(strat)
        var = sum((item - mean) ** 2 for item in strat) / len(strat)
        std = math.sqrt(var)
        sharpe = (mean / std) * math.sqrt(TRADING_DAYS_PER_YEAR) if std > 1e-12 else 0.0
    else:
        sharpe = 0.0

    ann = (1.0 + total_return) ** (TRADING_DAYS_PER_YEAR / max(len(strat), 1)) - 1.0 if equity > 0 else 0.0
    calmar = (ann / abs(max_dd)) if max_dd < 0 else 0.0
    win_rate, n_closed = _closed_round_win_rate(trades)
    return {
        "hist_win_rate": float(win_rate),
        "hist_total_trades": float(n_closed),
        "hist_return": float(total_return),
        "hist_sharpe_ratio": float(sharpe),
        "hist_max_drawdown": float(max_dd),
        "hist_calmar_ratio": float(calmar),
    }


def evaluate_bars(
    rows: Sequence[Mapping[str, Any]],
    *,
    regime_rule: str = DEFAULT_REGIME_RULE,
    confirm_days: int = CONFIRM_DAYS_DEFAULT,
    exit_confirm_days: int = EXIT_CONFIRM_DAYS_DEFAULT,
    min_bars: int = MIN_BARS,
) -> Optional[Dict[str, Any]]:
    """Turn daily OHLCV rows into pool trades + hist metrics. None if too short."""
    bars = [row for row in rows if _bar_date(row) and _bar_close(row) is not None]
    bars.sort(key=_bar_date)
    if len(bars) < int(min_bars):
        return None

    score_dates = [_bar_date(row) for row in bars]
    _, schedule = build_regime_cash_schedule(
        bars,
        score_dates,
        confirm_days=confirm_days,
        exit_confirm_days=exit_confirm_days,
        regime_rule=regime_rule,
    )
    close_by_date = {_bar_date(row): _bar_close(row) for row in bars}
    trades = trades_from_schedule(schedule, close_by_date)
    metrics = compute_path_metrics(bars, schedule, trades)
    last = bars[-1]
    return {
        "trades": trades,
        "metrics": metrics,
        "last_date": _bar_date(last),
        "last_close": _bar_close(last),
        "last_action": schedule[-1]["action"] if schedule else "cash",
        "last_label": schedule[-1].get("label") if schedule else "uncertain",
    }


def select_universe(
    members: Iterable[Mapping[str, Any]],
    infos: Mapping[str, Mapping[str, Any]],
    *,
    l1_codes: Sequence[str] = K_REGIME_SW_L1_CODES,
    list_date_before: str = "",
    skip_st: bool = True,
    limit: int = 0,
) -> List[Dict[str, str]]:
    """Join current SW L1 members to stock_info; drop ST and too-new listings."""
    allowed = {str(code).strip() for code in l1_codes if str(code).strip()}
    cutoff = yyyymmdd(list_date_before)
    seen = set()
    out: List[Dict[str, str]] = []
    for member in members:
        flag = str(member.get("is_new") or "Y").upper()
        if flag in {"N", "0", "FALSE"}:
            continue
        code = str(member.get("l1_code") or "").strip()
        if code not in allowed:
            continue
        symbol = str(member.get("con_code") or member.get("symbol") or "").strip()
        if not symbol or symbol in seen:
            continue
        info = infos.get(symbol) or infos.get(symbol.split(".")[0]) or {}
        name = str(info.get("name") or member.get("name") or "").strip()
        if skip_st and is_st_name(name):
            continue
        list_date = yyyymmdd(info.get("list_date"))
        if cutoff and list_date and list_date >= cutoff:
            continue
        seen.add(symbol)
        out.append(
            {
                "symbol": symbol,
                "name": name,
                "industry": str(member.get("l1_name") or info.get("sw_l1") or ""),
                "l1_code": code,
            }
        )
        if limit and len(out) >= int(limit):
            break
    out.sort(key=lambda item: item["symbol"])
    return out


def build_trade_docs(
    *,
    symbol: str,
    name: str,
    industry: str,
    preset: str,
    params: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    pool_start: str = "",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Mongo docs for strategy_trade_history and BUY-only strategy_stock_pool."""
    metrics = dict(evaluation.get("metrics") or {})
    hist_block = {
        "hist_win_rate": metrics.get("hist_win_rate", 0.0),
        "hist_total_trades": int(metrics.get("hist_total_trades") or 0),
        "hist_return": metrics.get("hist_return", 0.0),
        "hist_sharpe_ratio": metrics.get("hist_sharpe_ratio", 0.0),
        "hist_max_drawdown": metrics.get("hist_max_drawdown", 0.0),
        "hist_calmar_ratio": metrics.get("hist_calmar_ratio", 0.0),
    }
    cutoff = yyyymmdd(pool_start)
    history: List[Dict[str, Any]] = []
    pool: List[Dict[str, Any]] = []
    for trade in evaluation.get("trades") or []:
        date = yyyymmdd(trade.get("date"))
        action = str(trade.get("action") or "").upper()
        if not date or action not in {"BUY", "SELL"}:
            continue
        doc = {
            "date": date,
            "strategy": STRATEGY_KEY,
            "preset": preset,
            "symbol": symbol,
            "name": name,
            "industry": industry,
            "params_used": dict(params),
            "action": action,
            "price": trade.get("price"),
            "quantity": int(trade.get("quantity") or 0),
            "datetime": trade.get("datetime") or f"{date[:4]}-{date[4:6]}-{date[6:8]} 15:00:00",
            "pnl": trade.get("pnl", 0),
            "cumulative_pnl": trade.get("cumulative_pnl", 0),
            **hist_block,
        }
        history.append(doc)
        if action == "BUY" and (not cutoff or date >= cutoff):
            pool.append(
                {
                    "date": date,
                    "strategy": STRATEGY_KEY,
                    "preset": preset,
                    "symbol": symbol,
                    "name": name,
                    "industry": industry,
                    "params_used": dict(params),
                    "action": "BUY",
                    "price": trade.get("price"),
                    "last_datetime": doc["datetime"],
                    "last_label": evaluation.get("last_label"),
                    **hist_block,
                }
            )
    return history, pool


def strategy_template_doc(preset: str = DEFAULT_PRESET) -> Dict[str, Any]:
    return {
        "strategy": STRATEGY_KEY,
        "preset": preset,
        "is_default": preset == DEFAULT_PRESET,
        "params": dict(DEFAULT_PARAMS),
    }
