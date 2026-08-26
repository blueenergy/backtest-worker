#!/usr/bin/env python3
"""Unit tests for screening_scheduler schedule windows."""

from datetime import datetime
from unittest.mock import patch

import screening_scheduler as sched


def test_weekend_uses_360_day_window():
    saturday = datetime(2026, 8, 1, 10, 0, 0)  # Saturday
    with patch.object(sched, "MANUAL_DAYS_BACK", ""), \
         patch.object(sched, "MANUAL_RUN_AT", ""), \
         patch("screening_scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = saturday
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        hour, minute, days_back = sched.get_schedule()
    assert (hour, minute) == (8, 0)
    assert days_back == 360


def test_weekday_uses_250_day_window():
    monday = datetime(2026, 8, 3, 10, 0, 0)  # Monday
    with patch.object(sched, "MANUAL_DAYS_BACK", ""), \
         patch.object(sched, "MANUAL_RUN_AT", ""), \
         patch("screening_scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = monday
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        hour, minute, days_back = sched.get_schedule()
    assert (hour, minute) == (18, 30)
    assert days_back == 250


def test_manual_days_back_overrides_auto_window():
    with patch.object(sched, "MANUAL_DAYS_BACK", "400"), \
         patch.object(sched, "MANUAL_RUN_AT", "09:15"):
        hour, minute, days_back = sched.get_schedule()
    assert (hour, minute) == (9, 15)
    assert days_back == 400


def test_run_screening_passes_production_thresholds(monkeypatch):
    monkeypatch.setattr(sched, "acquire_screening_lock", lambda: True)
    monkeypatch.setattr(sched, "release_screening_lock", lambda: None)
    monkeypatch.setattr(sched, "get_tasks", lambda: [("hidden_dragon", "dragon_conservative")])
    calls = []

    class FakePopen:
        def __init__(self, cmd, **kw):
            calls.append(cmd)

        def wait(self):
            return 0

    monkeypatch.setattr(sched.subprocess, "Popen", FakePopen)
    sched.run_screening(180)
    cmd = calls[0]
    assert "--min-win-rate" in cmd and "0.50" in cmd
    assert "--min-trades" in cmd and "3" in cmd
    assert "--min-return" in cmd and "0.03" in cmd


def test_run_screening_env_thresholds_override(monkeypatch):
    monkeypatch.setattr(sched, "acquire_screening_lock", lambda: True)
    monkeypatch.setattr(sched, "release_screening_lock", lambda: None)
    monkeypatch.setattr(sched, "get_tasks", lambda: [("hidden_dragon", "dragon_conservative")])
    calls = []

    class FakePopen:
        def __init__(self, cmd, **kw):
            calls.append(cmd)

        def wait(self):
            return 0

    monkeypatch.setattr(sched, "SCREENING_MIN_WIN_RATE", "0.40")
    monkeypatch.setattr(sched, "SCREENING_MIN_TRADES", "2")
    monkeypatch.setattr(sched, "SCREENING_MIN_RETURN", "0.02")
    monkeypatch.setattr(sched.subprocess, "Popen", FakePopen)
    sched.run_screening(180)
    cmd = calls[0]
    assert "0.40" in cmd
    assert "2" in cmd
    assert "0.02" in cmd
