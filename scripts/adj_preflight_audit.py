#!/usr/bin/env python3
"""Read-only audit for stock_adj_factor coverage before enabling hard failures."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from stock_data_access.mongo_context import get_db
from stock_data_access.prices import AdjustedPriceDataAccess


def _sample_symbols(db, limit: int) -> list[str]:
    coll = db["volume_price"]
    pipeline = [
        {"$group": {"_id": "$symbol", "min_date": {"$min": "$trade_date"}, "max_date": {"$max": "$trade_date"}}},
        {"$sort": {"_id": 1}},
        {"$limit": limit},
    ]
    return [row["_id"] for row in coll.aggregate(pipeline)]


def audit(symbols: list[str], start_date: str, end_date: str) -> None:
    dao = AdjustedPriceDataAccess(db=get_db())
    failures = 0
    for symbol in symbols:
        df = dao.load_adjusted_ohlc(symbol, start_date, end_date, adjust="hfq")
        if df.empty:
            print(f"[EMPTY] {symbol}")
            failures += 1
            continue
        degraded = bool(df.attrs.get("adj_degraded", False))
        coverage = float(df.attrs.get("adj_coverage", 0.0))
        bfilled = bool(df.attrs.get("adj_bfilled", False))
        status = "OK"
        if degraded or coverage < 1.0 or bfilled:
            status = "FAIL"
            failures += 1
        print(
            f"[{status}] {symbol} bars={len(df)} "
            f"degraded={degraded} coverage={coverage:.4f} bfilled={bfilled}"
        )

    factor_min = dao.adj_coll.find_one({}, sort=[("trade_date", 1)])
    factor_max = dao.adj_coll.find_one({}, sort=[("trade_date", -1)])
    print("---")
    print(f"symbols_checked={len(symbols)} failures={failures}")
    if factor_min:
        print(f"stock_adj_factor earliest: {factor_min.get('trade_date')}")
    if factor_max:
        print(f"stock_adj_factor latest: {factor_max.get('trade_date')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit adj_factor coverage for backtests")
    parser.add_argument("--limit", type=int, default=30, help="Number of symbols to sample")
    parser.add_argument("--years", type=int, default=3, help="Lookback years from today")
    args = parser.parse_args()

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=365 * args.years)).strftime("%Y%m%d")
    db = get_db()
    symbols = _sample_symbols(db, args.limit)
    print(f"Auditing {len(symbols)} symbols from {start} to {end}")
    audit(symbols, start, end)


if __name__ == "__main__":
    main()
