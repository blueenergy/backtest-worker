"""Plotting utilities (moved from examples.plotting)."""

import re
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import matplotlib.pyplot as plt
import pandas as pd

# Skip CJK font setup if utils.env_setup is not available
try:
    from utils.env_setup import get_cjk_font
    _CJK_FP = get_cjk_font()
except ImportError:
    _CJK_FP = None
    print("[Warning] utils.env_setup not available, using default font")


def _sanitize(text: str) -> str:
    """Sanitize text for filesystem usage.

    Keeps alnum & Chinese chars, replaces others with underscore, collapses repeats, lowercases.
    """
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]+", "_", text or "")
    s = re.sub(r"_+", "_", s).strip("_")
    return s.lower() or "na"


def plot_symbol_close(
    df: pd.DataFrame,
    symbol: str,
    stock_name: str,
    events: Optional[Sequence[Mapping[str, Any]]] = None,
    output_dir: Optional[Path] = None,
    strategy_key: Optional[str] = None,
) -> Optional[Path]:
    if "close" not in df.columns:
        return None
    closes = df["close"].dropna()
    if closes.empty:
        return None
    norm_close = closes / closes.iloc[0]
    MAX_TABLE = 25
    has_table = (events is None) or (isinstance(events, (list, tuple)) and len(events) <= MAX_TABLE)
    fig_height = 10 if has_table else 4  # 原6，建议10
    fig = plt.figure(figsize=(8, fig_height))
    if has_table:
        gs = fig.add_gridspec(2, 1, height_ratios=[4, 1])
        ax = fig.add_subplot(gs[0])
        table_ax = fig.add_subplot(gs[1])
        table_ax.axis("off")
    else:
        ax = fig.add_subplot(111)
    norm_close.plot(ax=ax, label=f"{symbol} Close Norm")

    if events:
        events_list = list(events)
        base_dir = output_dir if output_dir else Path(".")
        base_dir.mkdir(parents=True, exist_ok=True)
        import pandas as pd

        trades_df = pd.DataFrame(
            [
                {
                    "idx": i + 1,
                    "datetime": ev.get("datetime"),
                    "action": ev.get("action"),
                    "size": ev.get("size"),
                    "price": ev.get("price"),
                    "position_after": ev.get("position_after"),
                    "avg_cost": ev.get("avg_cost"),
                    "realized_pl": ev.get("realized_pl"),
                    "cum_pl": ev.get("cum_pl"),
                    "unrealized_pl": ev.get("unrealized_pl"),
                    "total_pl": ev.get("total_pl"),
                }
                for i, ev in enumerate(events_list)
            ]
        )
        # Build filename pattern including symbol + optional strategy + sanitized stock name
        san_stock = _sanitize(stock_name)
        san_symbol = _sanitize(symbol)
        san_strategy = _sanitize(strategy_key) if strategy_key else None
        csv_parts = ["trades", san_symbol]
        if san_strategy:
            csv_parts.append(san_strategy)
        csv_parts.append(san_stock)
        csv_fname = "_".join(csv_parts) + ".csv"
        csv_path = base_dir / csv_fname
        try:
            trades_df.to_csv(csv_path, index=False)
            print(f"[Trades] Saved {len(trades_df)} executions to {csv_path}")
        except Exception as e:
            print(f"[Warn] Could not write trade CSV for {symbol}: {e}")
        idx_dt_map = {pd.to_datetime(d).to_pydatetime(): d for d in norm_close.index}
        vertical_slots = {}
        for i, ev in enumerate(events_list):
            dt = ev.get("datetime")
            if not dt:
                continue
            plot_dt = dt if dt in idx_dt_map else min(idx_dt_map.keys(), key=lambda x: abs(x - dt))
            label_date = idx_dt_map.get(plot_dt, None)
            if label_date is None:
                continue
            y_at = norm_close.loc[label_date]
            # If index has duplicates, loc may return a Series; take the last value
            y_val = y_at.iloc[-1] if isinstance(y_at, pd.Series) else y_at
            action = ev.get("action", "")
            color = "green" if action == "BUY" else "red"
            marker_style = "^" if action == "BUY" else "v"
            ax.scatter(plot_dt, y_val, color=color, marker=marker_style, s=45, zorder=5)  # type: ignore[arg-type]
            slot = vertical_slots.get(label_date, 0)
            vertical_slots[label_date] = slot + 1
            offset_pixels = 12 + slot * 8 * (-1 if action == "SELL" else 1)
            ax.annotate(
                str(i + 1),
                (plot_dt, y_val),
                textcoords="offset points",
                xytext=(0, offset_pixels),
                ha="center",
                fontsize=7,
                fontproperties=_CJK_FP if _CJK_FP else None,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.65, lw=0),
            )
        if has_table:
            table_rows = []
            for i, ev in enumerate(events_list):
                dt = ev.get("datetime")
                dt_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)
                price = ev.get("price")

                def fmt(v):
                    return f"{v:.2f}" if isinstance(v, (int, float)) else str(v)

                table_rows.append(
                    [
                        i + 1,
                        dt_str,
                        ev.get("action"),
                        ev.get("size"),
                        fmt(price),
                        ev.get("position_after"),
                        fmt(ev.get("avg_cost")),
                        fmt(ev.get("cum_pl")),
                        fmt(ev.get("unrealized_pl")),
                        fmt(ev.get("total_pl")),
                    ]
                )
            if not table_rows:
                table_rows = [["-", "-", "NoTrades", "-", "-", "-", "-", "-", "-", "-"]]
            col_labels = ["#", "Date", "Act", "Size", "Price", "Pos", "AvgCost", "CumPL", "UnrlPL", "TotPL"]
            table_ax2 = fig.axes[1] if has_table else None  # type: ignore
            if table_ax2 is not None:
                table = table_ax2.table(cellText=table_rows, colLabels=col_labels, loc="center")
                table.auto_set_font_size(False)
                table.set_fontsize(9)  # 原7，建议10
                table.scale(1, 1.25)  # 原1.05，建议1.25

    if _CJK_FP:
        ax.set_title(f"{symbol} {stock_name} Normalized Close", fontproperties=_CJK_FP)
        ax.legend(prop=_CJK_FP)
    else:
        ax.set_title(f"{symbol} {stock_name} Normalized Close")
        ax.legend()
    fig.tight_layout()
    base_dir = output_dir if output_dir else Path(".")
    san_stock = _sanitize(stock_name)
    san_symbol = _sanitize(symbol)
    san_strategy = _sanitize(strategy_key) if strategy_key else None
    plot_parts = ["backtrader_plot", san_symbol]
    if san_strategy:
        plot_parts.append(san_strategy)
    plot_parts.append(san_stock)
    out_path = base_dir / ("_".join(plot_parts) + ".png")
    fig.savefig(str(out_path))
    plt.close(fig)
    return out_path


def plot_portfolio_equity(price_map, symbols, initial_capital: float, output_dir: Path) -> Optional[Path]:
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
        print("[Portfolio] No close data to build equity curve.")
        return None
    closes_df = pd.concat(series_list, axis=1).dropna(how="any")
    if closes_df.empty:
        print("[Portfolio] Aligned close DataFrame empty.")
        return None
    n = closes_df.shape[1]
    capital_per = initial_capital / n
    first_row = closes_df.iloc[0]
    shares = capital_per / first_row
    portfolio_values = (closes_df * shares).sum(axis=1)
    equity_norm = portfolio_values / portfolio_values.iloc[0]
    plt.figure(figsize=(11, 6))
    ax = plt.gca()
    equity_norm.plot(ax=ax, label="Portfolio", color="black", linewidth=2)
    for sym in shares.index:
        indiv_norm = closes_df[sym] / closes_df[sym].iloc[0]
        indiv_norm.plot(ax=ax, alpha=0.55, linewidth=1, label=sym)
    legend_fontsize = 7 if len(shares.index) > 25 else 8
    if _CJK_FP:
        ax.set_title("等权组合与个股归一化曲线比较", fontproperties=_CJK_FP)
        ax.legend(loc="best", fontsize=legend_fontsize, prop=_CJK_FP, ncol=1 if len(shares.index) < 15 else 2)
    else:
        ax.set_title("Equal-Weight Portfolio vs Individual Normalized Closes")
        ax.legend(loc="best", fontsize=legend_fontsize, ncol=1 if len(shares.index) < 15 else 2)
    ax.set_ylabel("Normalized Value (Start=1.0)")
    ax.grid(alpha=0.25, linestyle="--")
    plt.tight_layout()
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "portfolio_equity_curve.png"
    plt.savefig(out_path)
    plt.close()
    print(f"[Portfolio] Equity curve saved to {out_path}")
    return out_path


__all__ = ["plot_symbol_close", "plot_portfolio_equity"]
