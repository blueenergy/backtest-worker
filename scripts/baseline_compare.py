#!/usr/bin/env python3
"""Run backtest baselines and export full metrics for the new engine口径."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from quant_strategies.strategies import STRATEGY_MAP
from worker.simple_backtest_runner import SimpleBacktestRunner

DEFAULT_SYMBOLS = [
    "600519.SH",
    "000858.SZ",
    "300750.SZ",
    "601318.SH",
    "000001.SZ",
]

DEFAULT_STRATEGIES = [
    "sma_cross",
    "mean_reversion",
    "turtle",
    "grid",
    "atr_breakout",
]

# All metrics produced by SimpleBacktestRunner._extract_metrics (+ invested fields).
METRIC_KEYS = [
    "total_return",
    "invested_return",
    "invested_cash",
    "capital_utilization",
    "sharpe_ratio",
    "max_drawdown",
    "max_drawdown_len",
    "win_rate",
    "total_trades",
    "calmar_ratio",
    "sortino_ratio",
    "sqn",
    "ulcer_index",
    "benchmark_return",
    "excess_return",
]


def _pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "—"


def _num(value: Optional[float], digits: int = 3) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _row_from_result(symbol: str, strategy: str, result: Dict[str, Any]) -> Dict[str, Any]:
    metrics = result.get("metrics", {}) or {}
    row: Dict[str, Any] = {
        "symbol": symbol,
        "strategy": strategy,
        "status": "ok",
        "trade_count": len(result.get("trades", []) or []),
    }
    for key in METRIC_KEYS:
        row[key] = metrics.get(key)
    return row


def run_baseline(
    symbols: List[str],
    strategy_keys: List[str],
    start_date: str,
    end_date: str,
    initial_cash: float,
) -> List[Dict[str, Any]]:
    runner = SimpleBacktestRunner()
    rows: List[Dict[str, Any]] = []
    for symbol in symbols:
        for key in strategy_keys:
            if key not in STRATEGY_MAP:
                rows.append(
                    {
                        "symbol": symbol,
                        "strategy": key,
                        "status": "error",
                        "error": f"unknown strategy key: {key}",
                    }
                )
                continue
            strategy_cls = STRATEGY_MAP[key]
            try:
                result = runner.run_backtest(
                    symbol=symbol,
                    strategy_class=strategy_cls,
                    start_date=start_date,
                    end_date=end_date,
                    initial_cash=initial_cash,
                )
                rows.append(_row_from_result(symbol, key, result))
            except Exception as exc:
                rows.append(
                    {
                        "symbol": symbol,
                        "strategy": key,
                        "status": "error",
                        "error": str(exc),
                    }
                )
    return rows


def write_json(rows: List[Dict[str, Any]], path: Path, meta: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "rows": rows}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote JSON: {path}")


def write_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["symbol", "strategy", "status"] + METRIC_KEYS + ["trade_count", "error"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"Wrote CSV: {path}")


def write_markdown(rows: List[Dict[str, Any]], path: Path, meta: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok_rows = [r for r in rows if r.get("status") == "ok"]
    err_rows = [r for r in rows if r.get("status") != "ok"]

    lines = [
        "# Backtest Baseline (new engine口径)",
        "",
        f"- Generated: {meta.get('generated_at')}",
        f"- Range: {meta.get('start_date')} → {meta.get('end_date')}",
        f"- Strategies: {', '.join(meta.get('strategies', []))}",
        f"- Symbols: {', '.join(meta.get('symbols', []))}",
        "",
        f"Success: **{len(ok_rows)}** / {len(rows)}",
        "",
        "| Symbol | Strategy | Return | MaxDD | Sharpe | Calmar | Sortino | SQN | Ulcer | Bench | Excess | Trades |",
        "|--------|----------|--------|-------|--------|--------|---------|-----|-------|-------|--------|--------|",
    ]
    for row in ok_rows:
        lines.append(
            "| {symbol} | {strategy} | {ret} | {dd} | {sharpe} | {calmar} | {sortino} | {sqn} | {ulcer} | {bench} | {excess} | {trades} |".format(
                symbol=row["symbol"],
                strategy=row["strategy"],
                ret=_pct(row.get("total_return")),
                dd=_pct(row.get("max_drawdown")),
                sharpe=_num(row.get("sharpe_ratio"), 2),
                calmar=_num(row.get("calmar_ratio"), 2),
                sortino=_num(row.get("sortino_ratio"), 2),
                sqn=_num(row.get("sqn"), 2),
                ulcer=_num(row.get("ulcer_index"), 2),
                bench=_pct(row.get("benchmark_return")),
                excess=_pct(row.get("excess_return")),
                trades=row.get("total_trades", "—"),
            )
        )

    if err_rows:
        lines.extend(["", "## Errors", ""])
        for row in err_rows:
            lines.append(f"- `{row['symbol']}` / `{row['strategy']}`: {row.get('error', 'unknown')}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote Markdown: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strategy baseline with full metrics")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    parser.add_argument("--strategies", nargs="*", default=DEFAULT_STRATEGIES)
    parser.add_argument("--start", default="20230101")
    parser.add_argument("--end", default="20231231")
    parser.add_argument("--cash", type=float, default=1_000_000)
    parser.add_argument("--output", default="scripts/baseline_results.json")
    parser.add_argument("--csv", default="scripts/baseline_results.csv")
    parser.add_argument("--md", default="scripts/baseline_results.md")
    args = parser.parse_args()

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_date": args.start,
        "end_date": args.end,
        "initial_cash": args.cash,
        "symbols": list(args.symbols),
        "strategies": list(args.strategies),
    }

    rows = run_baseline(args.symbols, args.strategies, args.start, args.end, args.cash)
    write_json(rows, Path(args.output), meta)
    write_csv(rows, Path(args.csv))
    write_markdown(rows, Path(args.md), meta)

    ok = sum(1 for r in rows if r.get("status") == "ok")
    print(f"Done: {ok}/{len(rows)} succeeded")


if __name__ == "__main__":
    main()
