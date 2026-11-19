from datetime import datetime, timedelta
from pathlib import Path

from worker.k_regime_pool import (
    DEFAULT_PRESET,
    STRATEGY_KEY,
    build_trade_docs,
    compute_path_metrics,
    evaluate_bars,
    is_st_name,
    select_universe,
    trades_from_schedule,
)


def _rows(start: str, closes, *, vol=1_000_000.0, high_pad=0.01, low_pad=0.01):
    dt = datetime.strptime(start, "%Y%m%d")
    rows = []
    for idx, close in enumerate(closes):
        trade_date = (dt + timedelta(days=idx)).strftime("%Y%m%d")
        rows.append(
            {
                "trade_date": trade_date,
                "open": close,
                "high": close * (1.0 + high_pad),
                "low": close * (1.0 - low_pad),
                "close": close,
                "vol": vol,
                "volume": vol,
            }
        )
    return rows


def test_is_st_name_catches_prefix_variants():
    assert is_st_name("*ST宇顺")
    assert is_st_name("ST长油")
    assert is_st_name("S*ST生化")
    assert not is_st_name("宁德时代")
    assert not is_st_name("生益科技")


def test_trades_from_schedule_records_flips_only():
    schedule = [
        {"score_date": "20240101", "action": "cash"},
        {"score_date": "20240102", "action": "cash"},
        {"score_date": "20240103", "action": "invest"},
        {"score_date": "20240104", "action": "invest"},
        {"score_date": "20240105", "action": "cash"},
    ]
    closes = {
        "20240101": 10.0,
        "20240102": 10.0,
        "20240103": 11.0,
        "20240104": 12.0,
        "20240105": 12.5,
    }
    trades = trades_from_schedule(schedule, closes)
    assert [item["action"] for item in trades] == ["BUY", "SELL"]
    assert trades[0]["date"] == "20240103"
    assert trades[0]["price"] == 11.0
    assert trades[1]["date"] == "20240105"
    assert trades[1]["pnl"] == 12.5 / 11.0 - 1.0


def test_initial_invest_is_not_a_buy():
    schedule = [
        {"score_date": "20240101", "action": "invest"},
        {"score_date": "20240102", "action": "invest"},
        {"score_date": "20240103", "action": "cash"},
    ]
    trades = trades_from_schedule(schedule, {"20240101": 10.0, "20240102": 11.0, "20240103": 9.0})
    assert [item["action"] for item in trades] == ["SELL"]
    assert trades[0]["date"] == "20240103"


def test_select_universe_keeps_five_l1_and_drops_st():
    members = [
        {"con_code": "300750.SZ", "l1_code": "801730.SI", "l1_name": "电力设备", "is_new": "Y"},
        {"con_code": "000001.SZ", "l1_code": "801780.SI", "l1_name": "银行", "is_new": "Y"},
        {"con_code": "002289.SZ", "l1_code": "801080.SI", "l1_name": "电子", "is_new": "Y"},
        {"con_code": "600105.SH", "l1_code": "801770.SI", "l1_name": "通信", "is_new": "N"},
    ]
    infos = {
        "300750.SZ": {"name": "宁德时代", "list_date": "20180611"},
        "002289.SZ": {"name": "*ST宇顺", "list_date": "20090903"},
        "000001.SZ": {"name": "平安银行", "list_date": "19910403"},
        "600105.SH": {"name": "永鼎股份", "list_date": "19970929"},
    }
    picked = select_universe(members, infos, list_date_before="20210101")
    assert [item["symbol"] for item in picked] == ["300750.SZ"]


def test_select_universe_drops_listings_on_or_after_cutoff():
    members = [
        {"con_code": "688981.SH", "l1_code": "801080.SI", "l1_name": "电子", "is_new": "Y"},
    ]
    infos = {"688981.SH": {"name": "中芯国际", "list_date": "20200716"}}
    assert select_universe(members, infos, list_date_before="20200716") == []
    assert select_universe(members, infos, list_date_before="20200717")[0]["symbol"] == "688981.SH"


def test_compute_path_metrics_counts_closed_wins():
    rows = [
        {"trade_date": "20240101", "close": 10.0},
        {"trade_date": "20240102", "close": 10.0},
        {"trade_date": "20240103", "close": 11.0},
        {"trade_date": "20240104", "close": 12.0},
        {"trade_date": "20240105", "close": 13.0},
        {"trade_date": "20240106", "close": 12.0},
    ]
    schedule = [
        {"score_date": "20240101", "action": "cash"},
        {"score_date": "20240102", "action": "invest"},
        {"score_date": "20240103", "action": "invest"},
        {"score_date": "20240104", "action": "invest"},
        {"score_date": "20240105", "action": "cash"},
        {"score_date": "20240106", "action": "cash"},
    ]
    trades = trades_from_schedule(
        schedule,
        {row["trade_date"]: row["close"] for row in rows},
    )
    metrics = compute_path_metrics(rows, schedule, trades)
    assert metrics["hist_total_trades"] == 1
    assert metrics["hist_win_rate"] == 1.0
    assert metrics["hist_return"] > 0


def test_evaluate_bars_emits_buy_on_confirmed_uptrend():
    warmup = [100.0 + idx * 0.02 for idx in range(160)]
    rally = [warmup[-1] * (1.04**idx) for idx in range(1, 40)]
    rows = _rows("20200101", warmup + rally, vol=2_000_000)
    result = evaluate_bars(rows, regime_rule="k_slow_anchor", confirm_days=5, min_bars=180)
    assert result is not None
    actions = [item["action"] for item in result["trades"]]
    assert "BUY" in actions
    assert result["last_action"] == "invest"


def test_evaluate_bars_returns_none_when_history_is_short():
    rows = _rows("20240101", [10.0, 11.0, 12.0])
    assert evaluate_bars(rows, min_bars=250) is None


def test_build_trade_docs_pool_is_buy_only_and_honors_lookback():
    evaluation = {
        "last_label": "bull",
        "metrics": {
            "hist_win_rate": 0.5,
            "hist_total_trades": 2,
            "hist_return": 0.1,
            "hist_sharpe_ratio": 0.8,
            "hist_max_drawdown": -0.2,
            "hist_calmar_ratio": 0.4,
        },
        "trades": [
            {"date": "20240103", "action": "BUY", "price": 10.0, "pnl": 0, "cumulative_pnl": 0},
            {"date": "20240120", "action": "SELL", "price": 11.0, "pnl": 0.1, "cumulative_pnl": 0.1},
            {"date": "20240210", "action": "BUY", "price": 12.0, "pnl": 0, "cumulative_pnl": 0.1},
        ],
    }
    history, pool = build_trade_docs(
        symbol="300750.SZ",
        name="宁德时代",
        industry="电力设备",
        preset=DEFAULT_PRESET,
        params={"regime_rule": "k_slow_anchor_with_vol_and_atr"},
        evaluation=evaluation,
        pool_start="20240201",
    )
    assert {doc["action"] for doc in history} == {"BUY", "SELL"}
    assert all(doc["strategy"] == STRATEGY_KEY for doc in history)
    assert [doc["date"] for doc in pool] == ["20240210"]
    assert pool[0]["industry"] == "电力设备"
    assert pool[0]["hist_calmar_ratio"] == 0.4


def test_screening_scheduler_runs_the_k_regime_scan():
    """The scan is scheduled by the screening loop, not by a scorer cron.

    It used to be a 21:00 entry in stock-scoring-system's scorer crontab, which
    made a stock-pool producer depend on the scoring service. The pool writes the
    same collections as strategy screening, so it runs inside that scheduler's
    distributed lock instead.
    """
    scheduler = Path(__file__).resolve().parents[1] / "screening_scheduler.py"
    text = scheduler.read_text(encoding="utf-8")
    assert "scan_k_regime_pool.py" in text
    assert "run_k_regime_pool()" in text
    # Must run inside run_screening, i.e. while the lock is held.
    body = text.split("def run_screening(", 1)[1].split("\ndef ", 1)[0]
    assert "run_k_regime_pool()" in body
