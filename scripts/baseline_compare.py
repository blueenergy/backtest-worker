#!/usr/bin/env python3
"""Compare backtest metrics before/after engine changes (manual baseline tool)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from quant_strategies.strategies import STRATEGY_MAP
from worker.simple_backtest_runner import SimpleBacktestRunner


DEFAULT_SYMBOLS = [
    "600519.SH",
    "000858.SZ",
    "300750.SZ",
    "601318.SH",
    "000001.SZ",
]


def run_baseline(symbols, strategy_keys, start_date, end_date, output: Path) -> None:
    runner = SimpleBacktestRunner()
    rows = []
    for symbol in symbols:
        for key in strategy_keys:
            strategy_cls = STRATEGY_MAP[key]
            try:
                result = runner.run_backtest(
                    symbol=symbol,
                    strategy_class=strategy_cls,
                    start_date=start_date,
                    end_date=end_date,
                )
                metrics = result.get("metrics", {})
                rows.append(
                    {
                        "symbol": symbol,
                        "strategy": key,
                        "total_return": metrics.get("total_return"),
                        "max_drawdown": metrics.get("max_drawdown"),
                        "total_trades": metrics.get("total_trades"),
                        "benchmark_return": metrics.get("benchmark_return"),
                        "excess_return": metrics.get("excess_return"),
                    }
                )
            except Exception as exc:
                rows.append({"symbol": symbol, "strategy": key, "error": str(exc)})

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} rows to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strategy baseline comparison")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    parser.add_argument("--strategies", nargs="*", default=["grid", "turtle", "sma_cross"])
    parser.add_argument("--start", default="20230101")
    parser.add_argument("--end", default="20231231")
    parser.add_argument("--output", default="scripts/baseline_results.json")
    args = parser.parse_args()
    run_baseline(args.symbols, args.strategies, args.start, args.end, Path(args.output))


if __name__ == "__main__":
    main()
