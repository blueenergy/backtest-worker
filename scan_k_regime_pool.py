#!/usr/bin/env python3
"""Scan five Shenwan L1 industries into the strategy stock pool.

Writes the same Mongo collections as daily_full_market_screening.py
(strategy_stock_pool / strategy_trade_history / strategy_template) under
strategy_key ``k_regime``. Buy and sell both come from
k_slow_anchor_with_vol_and_atr — not from hidden_dragon / turtle / single_yang.

Example:
    python tools/scan_k_regime_pool.py --dry-run --limit-symbols 20
    python tools/scan_k_regime_pool.py --workers 6
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Tuple

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = CURRENT_DIR  # this script lives at the repo root
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from worker.k_regime_pool import (  # noqa: E402
    DEFAULT_ADJUST,
    DEFAULT_PARAMS,
    DEFAULT_PRESET,
    DEFAULT_REGIME_RULE,
    K_REGIME_SW_L1_CODES,
    MIN_BARS,
    STRATEGY_KEY,
    build_trade_docs,
    evaluate_bars,
    select_universe,
    shift_calendar,
    strategy_template_doc,
    yyyymmdd,
)
from stock_data_access.regime import (  # noqa: E402
    CONFIRM_DAYS_DEFAULT,
    EXIT_CONFIRM_DAYS_DEFAULT,
)

log = logging.getLogger("scan_k_regime_pool")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan K+volume+NATR timing into the strategy pool")
    parser.add_argument("--start-date", default="20200101", help="YYYYMMDD bars start (default 20200101)")
    parser.add_argument("--end-date", default="", help="YYYYMMDD bars end (default today)")
    parser.add_argument("--pool-lookback-days", type=int, default=360, help="Only list BUY dates inside this window")
    parser.add_argument("--limit-symbols", type=int, default=0, help="Cap universe size for smoke tests")
    parser.add_argument("--workers", type=int, default=max(1, min(6, os.cpu_count() or 1)))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--adjust", default=DEFAULT_ADJUST, choices=["qfq", "hfq", "none"])
    parser.add_argument("--regime-rule", default=DEFAULT_REGIME_RULE)
    parser.add_argument("--confirm-days", type=int, default=CONFIRM_DAYS_DEFAULT)
    parser.add_argument("--exit-confirm-days", type=int, default=EXIT_CONFIRM_DAYS_DEFAULT)
    parser.add_argument("--min-bars", type=int, default=MIN_BARS)
    parser.add_argument("--list-date-before", default="20210101", help="Require listing strictly before this date")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def _load_universe(db, *, list_date_before: str, limit: int) -> List[Dict[str, str]]:
    members = list(
        db.sw_index_member.find(
            # is_new='Y' is required now that the collection also holds departed
            # stints: without it a stock appears once per historical assignment.
            {"src": "SW2021", "is_new": "Y", "l1_code": {"$in": list(K_REGIME_SW_L1_CODES)}},
            {"_id": 0, "con_code": 1, "symbol": 1, "l1_code": 1, "l1_name": 1, "is_new": 1},
        )
    )
    symbols = []
    for member in members:
        symbol = str(member.get("con_code") or member.get("symbol") or "").strip()
        if symbol:
            symbols.append(symbol)
            if "." not in symbol:
                symbols.append(symbol)
    infos: Dict[str, Dict[str, Any]] = {}
    if symbols:
        cursor = db.stock_info.find(
            {"$or": [{"ts_code": {"$in": symbols}}, {"symbol": {"$in": symbols}}]},
            {"_id": 0, "ts_code": 1, "symbol": 1, "name": 1, "list_date": 1, "sw_l1": 1},
        )
        for doc in cursor:
            payload = {
                "name": doc.get("name") or "",
                "list_date": doc.get("list_date") or "",
                "sw_l1": doc.get("sw_l1") or "",
            }
            for key in (doc.get("ts_code"), doc.get("symbol")):
                text = str(key or "").strip()
                if text:
                    infos[text] = payload
    return select_universe(members, infos, list_date_before=list_date_before, limit=limit)


def _evaluate_symbol(job: Dict[str, Any]) -> Dict[str, Any] | None:
    from data_manager import DatabaseManager

    db = DatabaseManager()
    try:
        rows = db.get_volume_price_data(
            job["symbol"],
            start_date=job["start_date"],
            end_date=job["end_date"],
            adjust=job["adjust"],
            projection={
                "_id": 0,
                "trade_date": 1,
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "vol": 1,
                "volume": 1,
            },
        )
    finally:
        try:
            db.client.close()
        except Exception:
            pass
    if not rows:
        return None
    evaluation = evaluate_bars(
        rows,
        regime_rule=job["regime_rule"],
        confirm_days=job["confirm_days"],
        exit_confirm_days=job["exit_confirm_days"],
        min_bars=job["min_bars"],
    )
    if evaluation is None:
        return None
    evaluation["symbol"] = job["symbol"]
    evaluation["name"] = job["name"]
    evaluation["industry"] = job["industry"]
    return evaluation


def _upsert_docs(coll, docs: List[Dict[str, Any]], keys: Tuple[str, ...]) -> int:
    written = 0
    now = datetime.utcnow()
    for doc in docs:
        filt = {key: doc[key] for key in keys}
        payload = dict(doc)
        payload["created_at"] = now
        coll.update_one(filt, {"$set": payload}, upsert=True)
        written += 1
    return written


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    end_date = yyyymmdd(args.end_date) or datetime.today().strftime("%Y%m%d")
    start_date = yyyymmdd(args.start_date) or "20200101"
    pool_start = shift_calendar(end_date, -int(args.pool_lookback_days))
    params = dict(DEFAULT_PARAMS)
    params.update(
        {
            "regime_rule": args.regime_rule,
            "confirm_days": args.confirm_days,
            "exit_confirm_days": args.exit_confirm_days,
            "price_adjust": args.adjust,
        }
    )

    from data_manager import DatabaseManager

    db = DatabaseManager()
    universe = _load_universe(db, list_date_before=args.list_date_before, limit=args.limit_symbols)
    log.info(
        "Universe %d symbols | %s -> %s | pool_start=%s | rule=%s | dry_run=%s",
        len(universe),
        start_date,
        end_date,
        pool_start,
        args.regime_rule,
        args.dry_run,
    )
    if not universe:
        log.error("Empty universe; aborting")
        return 1

    jobs = [
        {
            "symbol": item["symbol"],
            "name": item["name"],
            "industry": item["industry"],
            "start_date": start_date,
            "end_date": end_date,
            "confirm_days": args.confirm_days,
            "exit_confirm_days": args.exit_confirm_days,
            "min_bars": args.min_bars,
            "adjust": args.adjust,
            "regime_rule": args.regime_rule,
        }
        for item in universe
    ]

    results: List[Dict[str, Any]] = []
    errors = 0
    skipped = 0
    workers = max(1, int(args.workers))
    if workers == 1:
        for job in jobs:
            try:
                evaluation = _evaluate_symbol(job)
            except Exception:
                log.exception("Failed %s", job["symbol"])
                errors += 1
                continue
            if evaluation is None:
                skipped += 1
                continue
            results.append(evaluation)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_evaluate_symbol, job): job["symbol"] for job in jobs}
            done = 0
            for future in as_completed(futures):
                done += 1
                symbol = futures[future]
                try:
                    evaluation = future.result()
                except Exception:
                    log.exception("Failed %s", symbol)
                    errors += 1
                    continue
                if evaluation is None:
                    skipped += 1
                else:
                    results.append(evaluation)
                if done % 50 == 0:
                    log.info("Progress %d/%d", done, len(jobs))

    buy_days = 0
    history_n = 0
    pool_n = 0
    finance = db.db
    trade_coll = finance["strategy_trade_history"]
    pool_coll = finance["strategy_stock_pool"]
    tpl_coll = finance["strategy_template"]

    if not args.dry_run:
        tpl_coll.update_one(
            {"strategy": STRATEGY_KEY, "preset": DEFAULT_PRESET},
            {"$set": strategy_template_doc(DEFAULT_PRESET)},
            upsert=True,
        )

    latest_buys: List[str] = []
    for evaluation in results:
        history, pool = build_trade_docs(
            symbol=evaluation["symbol"],
            name=evaluation["name"],
            industry=evaluation["industry"],
            preset=DEFAULT_PRESET,
            params=params,
            evaluation=evaluation,
            pool_start=pool_start,
        )
        history_n += len(history)
        pool_n += len(pool)
        buy_days += sum(1 for doc in pool if doc["date"] == end_date)
        if pool:
            latest_buys.append(
                f"{evaluation['symbol']} {evaluation['name']} {evaluation['industry']} "
                f"last_buy={pool[-1]['date']} wr={evaluation['metrics']['hist_win_rate']:.1%}"
            )
        if args.dry_run:
            continue
        _upsert_docs(
            trade_coll,
            history,
            ("date", "strategy", "preset", "symbol", "datetime"),
        )
        _upsert_docs(
            pool_coll,
            pool,
            ("date", "strategy", "preset", "symbol"),
        )

    log.info(
        "Done. scanned=%d wrote_history=%d wrote_pool=%d skipped=%d errors=%d buys_on_end=%d",
        len(results),
        history_n,
        pool_n,
        skipped,
        errors,
        buy_days,
    )
    for line in latest_buys[:20]:
        log.info("sample %s", line)
    return 0 if results or not universe else 1


if __name__ == "__main__":
    raise SystemExit(main())
