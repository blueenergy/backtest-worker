"""Performance reporting utilities using quantstats (HTML report generation)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

try:
    import quantstats as qs  # type: ignore
    _QS_AVAILABLE = True
except Exception:  # pragma: no cover
    _QS_AVAILABLE = False


def build_portfolio_equity(price_map: Dict[str, pd.DataFrame], symbols: List[str], initial_capital: float) -> pd.Series:
    series_list = []
    for sym in symbols:
        df = price_map.get(sym)
        if df is None or not isinstance(df, pd.DataFrame):
            continue
        if "close" not in df.columns:
            continue
        ser = df["close"].dropna().copy()
        if ser.empty:
            continue
        ser.name = sym
        series_list.append(ser)
    if not series_list:
        return pd.Series(dtype="float64")
    closes_df = pd.concat(series_list, axis=1).dropna(how="any")
    if closes_df.empty:
        return pd.Series(dtype="float64")
    n = closes_df.shape[1]
    capital_per = initial_capital / n
    first_row = closes_df.iloc[0]
    shares = capital_per / first_row
    portfolio_values = (closes_df * shares).sum(axis=1)
    portfolio_values.name = "equity"
    return portfolio_values


def generate_quantstats_report(price_map: Dict[str, pd.DataFrame], symbols: List[str], initial_capital: float, output_dir: Path, title: str = "Strategy Portfolio") -> Path | None:
    """Generate an HTML performance report using quantstats.

    Returns the path to the generated report or None if failed/unavailable.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    equity = build_portfolio_equity(price_map, symbols, initial_capital)
    if equity.empty or len(equity) < 5:
        print("[QS] Insufficient equity series for report.")
        return None
    returns = equity.pct_change().dropna()
    report_path = output_dir / "quantstats_report.html"
    if not _QS_AVAILABLE:
        print("[QS] quantstats not installed. Skipping HTML generation. Install with 'pip install quantstats'.")
        return None
    try:
        # Extend pandas for convenience if needed
        qs.extend_pandas()  # type: ignore
        qs.reports.html(returns, output=str(report_path), title=title)
        print(f"[QS] HTML performance report saved to {report_path}")
        return report_path
    except Exception as e:  # pragma: no cover
        print(f"[QS] Failed to generate report: {e}")
        return None

__all__ = ["generate_quantstats_report", "build_portfolio_equity"]


def generate_quantstats_report_from_equity(equity_series: pd.Series, output_dir: Path, title: str = "Live Portfolio") -> Path | None:
    """Generate quantstats HTML report from an equity series directly.

    equity_series: pd.Series indexed by datetime-like, values are absolute equity.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    if equity_series.empty or len(equity_series) < 5:
        print("[QS] Insufficient equity series for live report.")
        return None
    returns = equity_series.sort_index().pct_change().dropna()
    report_path = output_dir / "live_quantstats_report.html"
    if not _QS_AVAILABLE:
        print("[QS] quantstats not installed. Skipping live HTML generation. Install with 'pip install quantstats'.")
        return None
    try:
        import quantstats as qs  # type: ignore
        qs.extend_pandas()  # type: ignore
        qs.reports.html(returns, output=str(report_path), title=title)
        print(f"[QS] Live HTML performance report saved to {report_path}")
        return report_path
    except Exception as e:  # pragma: no cover
        print(f"[QS] Failed to generate live report: {e}")
        return None

__all__.append("generate_quantstats_report_from_equity")
