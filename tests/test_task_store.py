"""Tests for MongoBacktestTaskStore atomic claim, lease, and fencing."""

from datetime import datetime, timedelta

import mongomock
import pytest

from worker.task_store import MongoBacktestTaskStore, WORKER_TYPE


@pytest.fixture
def store():
    client = mongomock.MongoClient()
    db = client["test_finance"]
    store = MongoBacktestTaskStore(db=db)
    # The unique index on lock_id is what makes lock contention observable, so
    # tests must run against the same indexes production creates at startup.
    store.ensure_indexes()
    return store


def _pending_task(task_id: str, created_at: datetime) -> dict:
    return {
        "task_id": task_id,
        "user_id": "user-1",
        "symbol": "000001.SZ",
        "asset_type": "stock",
        "strategy_key": "turtle",
        "preset": "turtle_conservative",
        "strategy_params": {},
        "start_date": "20230101",
        "end_date": "20231231",
        "initial_cash": 1000000.0,
        "status": "pending",
        "created_at": created_at,
    }


def test_atomic_claim_returns_distinct_tasks(store):
    store.backtest_tasks.insert_many(
        [
            _pending_task("t1", datetime(2026, 1, 1)),
            _pending_task("t2", datetime(2026, 1, 2)),
        ]
    )
    first = store.claim_task("worker-a")
    second = store.claim_task("worker-b")
    assert first and first["task_id"] == "t1"
    assert second and second["task_id"] == "t2"
    assert store.backtest_tasks.count_documents({"status": "claimed"}) == 2


def test_heartbeat_extends_lease(store):
    store.backtest_tasks.insert_one(_pending_task("t1", datetime(2026, 1, 1)))
    claimed = store.claim_task("worker-a")
    token = claimed["lease_token"]
    before = store.backtest_tasks.find_one({"task_id": "t1"})["lease_expires_at"]
    assert store.heartbeat("t1", "worker-a", token)
    after = store.backtest_tasks.find_one({"task_id": "t1"})["lease_expires_at"]
    assert after >= before


def test_fencing_blocks_stale_owner_writes(store):
    store.backtest_tasks.insert_one(_pending_task("t1", datetime(2026, 1, 1)))
    claimed = store.claim_task("worker-a")
    token_a = claimed["lease_token"]
    store.backtest_tasks.update_one(
        {"task_id": "t1"},
        {
            "$set": {
                "status": "cancelled",
                "lease_token": None,
                "lease_expires_at": None,
                "heartbeat_at": None,
            }
        },
    )
    ok = store.report_failure("t1", "worker-a", token_a, "should not apply")
    assert ok is False


def test_expired_lease_is_reclaimed(store):
    store.backtest_tasks.insert_one(_pending_task("t1", datetime(2026, 1, 1)))
    claimed = store.claim_task("worker-a")
    expired = datetime.now() - timedelta(seconds=30)
    store.backtest_tasks.update_one(
        {"task_id": "t1"},
        {"$set": {"lease_expires_at": expired}},
    )
    reclaimed = store.reset_expired_jobs()
    assert reclaimed == 1
    doc = store.backtest_tasks.find_one({"task_id": "t1"})
    assert doc["status"] == "pending"
    assert doc["worker_id"] is None
    assert claimed["lease_token"]


def test_legacy_claimed_task_without_lease_is_reclaimed(store):
    """Tasks claimed by a pre-lease worker used local-time stamps."""
    stale = datetime.now() - timedelta(hours=2)
    store.backtest_tasks.insert_one(
        {
            **_pending_task("t1", datetime(2026, 1, 1)),
            "status": "claimed",
            "worker_id": "old-worker",
            "started_at": stale,
        }
    )
    assert store.reset_expired_jobs() == 1
    doc = store.backtest_tasks.find_one({"task_id": "t1"})
    assert doc["status"] == "pending"
    assert doc["worker_id"] is None


def test_claim_writes_timestamps_in_api_local_time(store):
    """Worker and quantFinance must agree on the clock or leases skew by the UTC offset."""
    store.backtest_tasks.insert_one(_pending_task("t1", datetime(2026, 1, 1)))
    store.claim_task("worker-a")
    doc = store.backtest_tasks.find_one({"task_id": "t1"})
    # BSON truncates to milliseconds, so compare with a tolerance far smaller
    # than any UTC offset this would regress to.
    assert abs((doc["started_at"] - datetime.now()).total_seconds()) < 60
    assert doc["lease_expires_at"] > datetime.now()


def test_release_task_returns_to_pending(store):
    store.backtest_tasks.insert_one(_pending_task("t1", datetime(2026, 1, 1)))
    claimed = store.claim_task("worker-a")
    released = store.release_task("t1", "worker-a", claimed["lease_token"], "shutdown")
    assert released
    doc = store.backtest_tasks.find_one({"task_id": "t1"})
    assert doc["status"] == "pending"
    assert doc["worker_id"] is None


def test_screening_lock_is_singleton(store):
    assert store.acquire_screening_lock("holder-a", ttl_seconds=600)
    assert not store.acquire_screening_lock("holder-b", ttl_seconds=600)
    store.release_screening_lock("holder-a")
    assert store.acquire_screening_lock("holder-b", ttl_seconds=600)
    assert store.screening_locks.count_documents({}) == 1


def test_screening_lock_reacquires_after_ttl_expiry(store):
    assert store.acquire_screening_lock("holder-a", ttl_seconds=600)
    store.screening_locks.update_one(
        {"holder_id": "holder-a"},
        {"$set": {"expires_at": datetime.now() - timedelta(seconds=1)}},
    )
    assert store.acquire_screening_lock("holder-b", ttl_seconds=600)


def test_screening_lock_is_reentrant_for_same_holder(store):
    assert store.acquire_screening_lock("holder-a", ttl_seconds=600)
    assert store.acquire_screening_lock("holder-a", ttl_seconds=600)


def test_worker_status_records_pending_depth(store):
    store.backtest_tasks.insert_one(_pending_task("t1", datetime(2026, 1, 1)))
    store.record_worker_status("worker-a", "idle")
    doc = store.worker_status.find_one({"worker_type": WORKER_TYPE, "worker_id": "worker-a"})
    assert doc["pending_tasks"] == 1
