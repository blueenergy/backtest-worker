#!/usr/bin/env python3
"""Daily full-market screening job for Hidden Dragon (and other) strategies.

This script runs backtests over a universe of symbols using backtest-worker's
SimpleBacktestRunner (quant-strategies + data-access-lib) and writes
"today has BUY signal" candidates into MongoDB, so that the frontend can
render a strategy stock pool.

Key behavior:
- Universe: all symbols from `stock_info.symbol` (via StockPriceDataAccess)
- Data: daily bars via data-access-lib (StockPriceDataAccess, minute=False)
- Engine: SimpleBacktestRunner (Backtrader under the hood)
- Strategy: default `hidden_dragon`, but can be overridden via CLI
- Output: Mongo collection `strategy_stock_pool` with one document per
  (date, strategy, symbol)

Usage (example):
    cd backtest-worker
    python daily_full_market_screening.py \
        --strategy-key hidden_dragon \
        --days-back 180 \
        --initial-cash 1000000

You can also limit symbols for quick testing:
    python daily_full_market_screening.py --limit-symbols 50 --dry-run
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta
from typing import List

from stock_data_access import StockPriceDataAccess, get_trading_dates
from stock_data_access.mongo_context import get_db

from worker.simple_backtest_runner import SimpleBacktestRunner
from quant_strategies.strategies import STRATEGY_MAP


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Daily full-market screening using SimpleBacktestRunner"
    )

    parser.add_argument(
        "--strategy-key",
        default="hidden_dragon",
        choices=list(STRATEGY_MAP.keys()),
        help="Strategy key from quant_strategies.STRATEGY_MAP (default: hidden_dragon)",
    )

    parser.add_argument(
        "--preset",
        default=None,
        type=str,
        help="Optional preset name (e.g., turtle_selective, yang_selective). "
             "If provided, uses preset parameters instead of defaults.",
    )

    parser.add_argument(
        "--days-back",
        type=int,
        default=180,
        help="Number of calendar days to look back for backtest window (default: 180)",
    )

    parser.add_argument(
        "--initial-cash",
        type=float,
        default=1_000_000.0,
        help="Initial cash for each single-symbol backtest (default: 1,000,000)",
    )

    parser.add_argument(
        "--limit-symbols",
        type=int,
        default=0,
        help="Optional cap on number of symbols (for testing). 0 means no limit.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run screening but do NOT write to Mongo; only log candidates.",
    )

    parser.add_argument(
        "--sync-all",
        action="store_true",
        help="If set, sync all BUY signals found in the backtest period to Mongo. "
             "If False (default), only sync signals from the latest day.",
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    parser.add_argument(
        "--min-win-rate",
        type=float,
        default=0.0,
        help="Minimum historical win-rate (0.0-1.0) to include stock. "
             "Example: 0.5 = require 50%% win-rate. Default: 0.0 (no filter)",
    )

    parser.add_argument(
        "--min-trades",
        type=int,
        default=2,
        help="Minimum number of historical trades required for filtering. "
             "Stocks with fewer trades are excluded from win-rate filtering. Default: 2",
    )

    parser.add_argument(
        "--min-return",
        type=float,
        default=None,
        help="Minimum historical total return (decimal) to include stock. "
             "Example: 0.05 = require 5%% return. Default: None (no filter)",
    )

    return parser.parse_args()


def _init_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def _get_date_range(days_back: int) -> tuple[str, str]:
    """Compute (start_date, end_date) in YYYYMMDD.

    start_date: today - days_back (calendar);
    end_date: last trading day <= today (using trading calendar).
    """
    today = datetime.today().date()
    calendar_start = (today - timedelta(days=days_back)).strftime("%Y%m%d")
    calendar_end = today.strftime("%Y%m%d")

    # Prefer trading calendar (tushare -> Mongo fallback)
    trading_days = get_trading_dates(calendar_start, calendar_end)
    if trading_days:
        end = trading_days[-1]
        return calendar_start, end

    # Fallback: use calendar dates if no trading calendar available
    return calendar_start, calendar_end


def _load_universe_symbols(loader: StockPriceDataAccess, limit: int = 0) -> List[str]:
    """Load full symbol universe from stock_info.

    Uses `stock_info.symbol` as the canonical symbol (with suffix).
    """
    info_coll = loader.info_coll
    symbols = [s for s in info_coll.distinct("symbol") if isinstance(s, str) and s.strip()]
    symbols.sort()
    if limit and limit > 0:
        return symbols[:limit]
    return symbols


def main() -> None:
    args = _parse_args()
    _init_logging(args.log_level)
    log = logging.getLogger("daily_full_market_screening")

    strategy_key: str = args.strategy_key
    preset_name: str = args.preset
    days_back: int = args.days_back
    initial_cash: float = args.initial_cash
    limit_symbols: int = args.limit_symbols
    dry_run: bool = args.dry_run

    if strategy_key not in STRATEGY_MAP:
        raise SystemExit(f"Unknown strategy-key '{strategy_key}'. Available: {list(STRATEGY_MAP.keys())}")

    strategy_class = STRATEGY_MAP[strategy_key]
    
    # Load preset parameters if specified
    strategy_params = None
    if preset_name:
        try:
            from quant_strategies.strategy_params import get_preset
            strategy_params = get_preset(preset_name)
            log.info("Using preset: %s", preset_name)
        except Exception as e:
            log.warning("Failed to load preset '%s': %s. Using default parameters.", preset_name, e)
    
    sync_all: bool = args.sync_all
    log.info("Starting daily full-market screening | strategy=%s preset=%s days_back=%d sync_all=%s initial_cash=%.2f",
             strategy_key, preset_name or "default", days_back, sync_all, initial_cash)

    start_date, end_date = _get_date_range(days_back)
    log.info("Backtest window: %s -> %s", start_date, end_date)

    # 1) Load universe symbols via data-access-lib
    loader = StockPriceDataAccess(minute=False)
    symbols = _load_universe_symbols(loader, limit=limit_symbols)
    if not symbols:
        log.error("No symbols found in stock_info; aborting.")
        return

    log.info("Universe size: %d symbols%s",
             len(symbols), " (limited)" if limit_symbols and limit_symbols > 0 else "")

    # 2) Prepare backtest runner and Mongo collection
    runner = SimpleBacktestRunner()
    db = get_db()
    pool_coll = db["strategy_stock_pool"]

    total = 0
    candidates = 0
    skipped_no_data = 0
    skipped_performance = 0  # NEW: track filtered by performance
    errors = 0

    # For end_date comparison
    end_date_str = end_date  # YYYYMMDD

    for sym in symbols:
        total += 1
        try:
            log.debug("Running backtest for %s", sym)
            results = runner.run_backtest(
                symbol=sym,
                strategy_class=strategy_class,
                strategy_params=strategy_params,
                start_date=start_date,
                end_date=end_date,
                initial_cash=initial_cash,
            )
        except ValueError as e:
            # Common case: "No data found" or insufficient data
            msg = str(e)
            if "No data found" in msg:
                skipped_no_data += 1
                log.debug("Skip %s: %s", sym, msg)
                continue
            log.warning("ValueError for %s: %s", sym, msg)
            errors += 1
            continue
        except Exception as e:  # noqa: BLE001
            log.warning("Backtest failed for %s: %s", sym, e, exc_info=True)
            errors += 1
            continue

        trades = results.get("trades", []) or []
        if not trades:
            continue

        # Extract historical performance metrics
        metrics = results.get("metrics", {})
        hist_win_rate = metrics.get("win_rate", 0)
        hist_total_trades = metrics.get("total_trades", 0)
        hist_return = metrics.get("total_return", 0)
        
        # Apply historical performance filters
        min_win_rate = args.min_win_rate
        min_trades = args.min_trades
        min_return = args.min_return
        
        # Skip if insufficient trade history for meaningful filtering
        if hist_total_trades < min_trades:
            log.debug(f"Skip {sym}: insufficient trades ({hist_total_trades} < {min_trades})")
            skipped_performance += 1
            continue
        
        # Apply win-rate filter
        if min_win_rate > 0 and hist_win_rate < min_win_rate:
            log.debug(f"Skip {sym}: low win-rate ({hist_win_rate:.1%} < {min_win_rate:.1%})")
            skipped_performance += 1
            continue
        
        # Apply return filter
        if min_return is not None and hist_return < min_return:
            log.debug(f"Skip {sym}: low return ({hist_return:.2%} < {min_return:.2%})")
            skipped_performance += 1
            continue
        
        log.info(f"[QUALIFIED] {sym}: win_rate={hist_win_rate:.1%}, trades={hist_total_trades}, return={hist_return:.2%}")

        # Lookup name once for all records
        name_map = loader.fetch_names([sym])
        stock_name = name_map.get(sym, "")

        # Save ALL trades (buy + sell) for K-line chart display
        all_trades = results.get("trades", []) or []
        for tr in all_trades:
            dt_str = tr.get("datetime")  # 'YYYY-MM-DD HH:MM:SS'
            action = (tr.get("action") or "").lower()
            if not dt_str or not isinstance(dt_str, str):
                continue
            
            date_part = dt_str.split(" ", 1)[0].replace("-", "")  # YYYYMMDD
            
            # Save ALL BUY signals to strategy_stock_pool (not just today)
            # This allows users to browse historical buy signals in the frontend
            is_buy_signal = (action == "buy")
            
            # Always save to trade history collection
            trade_doc = {
                "date": date_part,
                "strategy": strategy_key,
                "preset": preset_name or "default",
                "symbol": sym,
                "name": stock_name,
                "action": action.upper(),  # BUY or SELL
                "price": tr.get("price"),
                "quantity": tr.get("quantity", 0),
                "datetime": dt_str,
                "pnl": tr.get("pnl", 0),
                "cumulative_pnl": tr.get("cumulative_pnl", 0),
                "created_at": datetime.utcnow(),
                # Historical metrics (same for all trades of this symbol)
                "hist_win_rate": hist_win_rate,
                "hist_total_trades": hist_total_trades,
                "hist_return": hist_return,
                "hist_sharpe_ratio": metrics.get("sharpe_ratio", 0),
                "hist_max_drawdown": metrics.get("max_drawdown", 0),
            }
            
            if not dry_run:
                # Save to trade history collection
                trade_history_coll = db["strategy_trade_history"]
                trade_history_coll.update_one(
                    {"date": date_part, "strategy": strategy_key, "preset": preset_name or "default", 
                     "symbol": sym, "datetime": dt_str},
                    {"$set": trade_doc},
                    upsert=True,
                )
            
            # If it's a BUY signal, save to stock pool (for frontend selection list)
            if is_buy_signal:
                # Only count signals from the latest date for statistics
                if date_part == end_date_str:
                    candidates += 1
                    log.info("[CANDIDATE] %s has BUY signal on %s (today)", sym, date_part)
                else:
                    log.debug("[HISTORICAL] %s had BUY signal on %s", sym, date_part)
                
                if not dry_run:
                    pool_doc = {
                        "date": date_part,
                        "strategy": strategy_key,
                        "preset": preset_name or "default",
                        "symbol": sym,
                        "name": stock_name,
                        "action": "BUY",
                        "price": tr.get("price"),
                        "last_datetime": dt_str,
                        "created_at": datetime.utcnow(),
                        # Historical performance metrics
                        "hist_win_rate": hist_win_rate,
                        "hist_total_trades": hist_total_trades,
                        "hist_return": hist_return,
                        "hist_sharpe_ratio": metrics.get("sharpe_ratio", 0),
                        "hist_max_drawdown": metrics.get("max_drawdown", 0),
                    }
                    
                    pool_coll.update_one(
                        {"date": date_part, "strategy": strategy_key, "preset": preset_name or "default", "symbol": sym},
                        {"$set": pool_doc},
                        upsert=True,
                    )

    log.info(
        "Screening done. symbols=%d candidates=%d skipped_no_data=%d skipped_performance=%d errors=%d",
        total,
        candidates,
        skipped_no_data,
        skipped_performance,
        errors,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
