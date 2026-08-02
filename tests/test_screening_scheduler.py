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
