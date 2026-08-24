"""MongoDB task queue with atomic claim, lease fencing, and heartbeat."""

from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

log = logging.getLogger(__name__)

WORKER_TYPE = "backtest_queue"
LOCK_COLLECTION = "backtest_screening_locks"
SCREENING_LOCK_ID = "screening_singleton"


def _now() -> datetime:
    """Local time, matching what quantFinance writes into backtest_tasks.

    Mixing naive UTC here with the API's local timestamps would make lease
    comparisons against API-written fields off by the container's UTC offset.
    """
    return datetime.now()


def _lease_seconds() -> int:
    return max(30, int(os.getenv("BACKTEST_LEASE_SECONDS", "300")))


def _heartbeat_seconds() -> int:
    return max(5, int(os.getenv("BACKTEST_HEARTBEAT_SECONDS", "30")))


def _legacy_stale_seconds() -> int:
    return max(_lease_seconds(), int(os.getenv("BACKTEST_LEGACY_STALE_SECONDS", "600")))


def _clean_for_mongo(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, datetime)):
        return value
    if isinstance(value, float):
        import math

        return value if math.isfinite(value) else None
    if isinstance(value, int):
        if -(2 ** 63) <= value <= (2 ** 63 - 1):
            return value
        return str(value)
    if isinstance(value, dict):
        return {str(k): _clean_for_mongo(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_for_mongo(v) for v in value]
    if hasattr(value, "item"):
        try:
            return _clean_for_mongo(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


class HeartbeatTicker:
    """Background lease renewal for long-running backtests."""

    def __init__(self, store: "MongoBacktestTaskStore", task_id: str, worker_id: str, lease_token: str) -> None:
        self._store = store
        self._task_id = task_id
        self._worker_id = worker_id
        self._lease_token = lease_token
        self._interval = float(_heartbeat_seconds())
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _beat_once(self) -> None:
        self._store.heartbeat(self._task_id, self._worker_id, self._lease_token)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._beat_once()
            except Exception as exc:  # pragma: no cover - best effort
                log.warning("heartbeat ticker error for %s: %s", self._task_id, exc)

    def start(self) -> "HeartbeatTicker":
        if self._interval > 0 and self._thread is None:
            self._thread = threading.Thread(
                target=self._run,
                name=f"backtest-heartbeat-{self._task_id}",
                daemon=True,
            )
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None


class MongoBacktestTaskStore:
    """MongoDB-backed task queue for backtest workers."""

    def __init__(
        self,
        mongo_uri: Optional[str] = None,
        db_name: Optional[str] = None,
        db: Any = None,
    ):
        self.mongo_uri = mongo_uri or os.getenv("MONGO_URI", "mongodb://localhost:27017")
        self.db_name = db_name or os.getenv("BACKTEST_DB_NAME") or os.getenv("DB_NAME") or "finance"
        self._client = None if db is not None else MongoClient(self.mongo_uri)
        self.db = db if db is not None else self._client[self.db_name]
        self.backtest_tasks = self.db["backtest_tasks"]
        self.backtest_results = self.db["backtest_results"]
        self.worker_status = self.db["worker_status"]
        self.screening_locks = self.db[LOCK_COLLECTION]

    def ensure_indexes(self) -> None:
        self.backtest_tasks.create_index(
            [("status", ASCENDING), ("created_at", ASCENDING)],
            name="backtest_tasks_status_created",
        )
        self.backtest_tasks.create_index(
            [("lease_expires_at", ASCENDING)],
            name="backtest_tasks_lease_expires",
            sparse=True,
        )
        self.worker_status.create_index(
            [("worker_type", ASCENDING), ("worker_id", ASCENDING)],
            unique=True,
            name="worker_status_type_id",
        )
        self.worker_status.create_index(
            [("last_seen_at", DESCENDING)],
            name="worker_status_last_seen",
        )
        self.screening_locks.create_index(
            [("lock_id", ASCENDING)],
            unique=True,
            name="screening_lock_id",
        )

    def pending_count(self) -> int:
        return int(
            self.backtest_tasks.count_documents(
                {
                    "status": "pending",
                    "start_date": {"$nin": ["", None]},
                    "end_date": {"$nin": ["", None]},
                }
            )
        )

    def claim_task(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """Atomically claim the oldest valid pending task."""
        now = _now()
        lease_token = f"{worker_id}:{uuid.uuid4().hex[:8]}"
        lease_expires_at = now + timedelta(seconds=_lease_seconds())
        task = self.backtest_tasks.find_one_and_update(
            {
                "status": "pending",
                "start_date": {"$nin": ["", None]},
                "end_date": {"$nin": ["", None]},
            },
            {
                "$set": {
                    "status": "claimed",
                    "worker_id": worker_id,
                    "started_at": now,
                    "updated_at": now,
                    "heartbeat_at": now,
                    "lease_token": lease_token,
                    "lease_expires_at": lease_expires_at,
                },
                "$inc": {"attempts": 1},
            },
            sort=[("created_at", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )
        if not task:
            return None
        return self._task_view(task)

    def heartbeat(self, task_id: str, worker_id: str, lease_token: str) -> bool:
        now = _now()
        lease_expires_at = now + timedelta(seconds=_lease_seconds())
        result = self.backtest_tasks.update_one(
            {
                "task_id": task_id,
                "worker_id": worker_id,
                "lease_token": lease_token,
                "status": "claimed",
            },
            {
                "$set": {
                    "heartbeat_at": now,
                    "lease_expires_at": lease_expires_at,
                    "updated_at": now,
                }
            },
        )
        return (result.modified_count or result.matched_count) > 0

    def release_task(
        self,
        task_id: str,
        worker_id: str,
        lease_token: str,
        message: str,
    ) -> bool:
        now = _now()
        result = self.backtest_tasks.update_one(
            {
                "task_id": task_id,
                "worker_id": worker_id,
                "lease_token": lease_token,
                "status": "claimed",
            },
            {
                "$set": {
                    "status": "pending",
                    "worker_id": None,
                    "started_at": None,
                    "error_message": message,
                    "updated_at": now,
                    "heartbeat_at": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                }
            },
        )
        return result.modified_count > 0

    def reset_expired_jobs(self) -> int:
        """Reclaim claimed tasks whose lease expired or legacy running orphans."""
        now = _now()
        expired_filter = {
            "status": {"$in": ["claimed", "running"]},
            "lease_expires_at": {"$lt": now},
        }
        expired = self.backtest_tasks.update_many(
            expired_filter,
            {
                "$set": {
                    "status": "pending",
                    "worker_id": None,
                    "started_at": None,
                    "error_message": "requeued after lease expired",
                    "updated_at": now,
                    "heartbeat_at": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                }
            },
        )
        legacy_cutoff = now - timedelta(seconds=_legacy_stale_seconds())
        legacy_filter = {
            "status": {"$in": ["claimed", "running"]},
            "lease_expires_at": {"$exists": False},
            "$or": [
                {"heartbeat_at": {"$lt": legacy_cutoff}},
                {"heartbeat_at": {"$exists": False}, "updated_at": {"$lt": legacy_cutoff}},
                {
                    "heartbeat_at": {"$exists": False},
                    "updated_at": {"$exists": False},
                    "started_at": {"$lt": legacy_cutoff},
                },
            ],
        }
        legacy = self.backtest_tasks.update_many(
            legacy_filter,
            {
                "$set": {
                    "status": "pending",
                    "worker_id": None,
                    "started_at": None,
                    "error_message": "requeued after legacy stale timeout",
                    "updated_at": now,
                    "heartbeat_at": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                }
            },
        )
        total = int(expired.modified_count or 0) + int(legacy.modified_count or 0)
        if total:
            log.info("Reclaimed %d expired/stale backtest tasks", total)
        return total

    def requeue_own_orphans(self, worker_id: str) -> int:
        now = _now()
        result = self.backtest_tasks.update_many(
            {"status": "claimed", "worker_id": worker_id},
            {
                "$set": {
                    "status": "pending",
                    "worker_id": None,
                    "started_at": None,
                    "error_message": f"requeued after worker {worker_id} restarted",
                    "updated_at": now,
                    "heartbeat_at": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                }
            },
        )
        return int(result.modified_count or 0)

    def _owner_filter(self, task_id: str, worker_id: str, lease_token: str) -> Dict[str, Any]:
        return {
            "task_id": task_id,
            "worker_id": worker_id,
            "lease_token": lease_token,
            "status": {"$in": ["claimed", "running"]},
        }

    def report_success(
        self,
        task_id: str,
        worker_id: str,
        lease_token: str,
        results: Dict[str, Any],
    ) -> bool:
        owner = self._owner_filter(task_id, worker_id, lease_token)
        task = self.backtest_tasks.find_one(owner)
        if not task:
            log.error("Cannot report success for %s: lost lease or task not owned", task_id)
            return False
        if task.get("status") == "cancelled":
            log.warning("Task %s was cancelled; skipping success report", task_id)
            return False

        result_doc = _clean_for_mongo(
            {
                "task_id": task_id,
                "user_id": task.get("user_id"),
                "symbol": task.get("symbol"),
                "asset_type": (task.get("asset_type") or "stock").lower(),
                "strategy_key": task.get("strategy_key"),
                "preset": task.get("preset"),
                "strategy_params": task.get("strategy_params", {}),
                "batch_id": task.get("batch_id"),
                "metrics": results.get("metrics", {}),
                "trades": results.get("trades", []),
                "equity_curve": results.get("equity_curve", []),
                "created_at": _now(),
            }
        )

        try:
            self.backtest_results.update_one(
                {"task_id": task_id},
                {"$set": result_doc},
                upsert=True,
            )
            now = _now()
            complete = self.backtest_tasks.update_one(
                owner,
                {
                    "$set": {
                        "status": "completed",
                        "completed_at": now,
                        "updated_at": now,
                        "heartbeat_at": None,
                        "lease_token": None,
                        "lease_expires_at": None,
                    }
                },
            )
            return complete.modified_count > 0
        except Exception as exc:
            log.error("Failed to persist backtest result for %s: %s", task_id, exc, exc_info=True)
            self.report_failure(task_id, worker_id, lease_token, f"Failed to persist backtest result: {exc}")
            return False

    def report_failure(
        self,
        task_id: str,
        worker_id: str,
        lease_token: str,
        error_message: str,
    ) -> bool:
        owner = self._owner_filter(task_id, worker_id, lease_token)
        task = self.backtest_tasks.find_one(owner)
        if not task:
            log.warning("Cannot report failure for %s: lost lease or task not owned", task_id)
            return False
        if task.get("status") == "cancelled":
            log.warning("Task %s was cancelled; skipping failure report", task_id)
            return False

        now = _now()
        result = self.backtest_tasks.update_one(
            owner,
            {
                "$set": {
                    "status": "failed",
                    "error_message": error_message or "Backtest failed",
                    "completed_at": now,
                    "updated_at": now,
                    "heartbeat_at": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                }
            },
        )
        return result.modified_count > 0

    def record_worker_status(
        self,
        worker_id: str,
        status: str,
        fields: Optional[Dict[str, Any]] = None,
        increments: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = _now()
        update: Dict[str, Any] = {
            "$set": {
                "worker_id": worker_id,
                "worker_type": WORKER_TYPE,
                "status": status,
                "last_seen_at": now,
                "updated_at": now,
                "pending_tasks": self.pending_count(),
                **(fields or {}),
            },
            "$setOnInsert": {"created_at": now},
        }
        if increments:
            update["$inc"] = increments
        self.worker_status.update_one(
            {"worker_type": WORKER_TYPE, "worker_id": worker_id},
            update,
            upsert=True,
        )

    def acquire_screening_lock(self, holder_id: str, ttl_seconds: int = 3600) -> bool:
        """Take the singleton screening lock, or return False if someone holds it.

        When another holder owns an unexpired lock the filter matches nothing and
        the upsert tries to insert a second lock document, which the unique index
        on lock_id rejects. That is the contended case, not an error.
        """
        now = _now()
        expires_at = now + timedelta(seconds=ttl_seconds)
        try:
            doc = self.screening_locks.find_one_and_update(
                {
                    "lock_id": SCREENING_LOCK_ID,
                    "$or": [
                        {"expires_at": {"$lt": now}},
                        {"expires_at": None},
                        {"expires_at": {"$exists": False}},
                        {"holder_id": holder_id},
                    ],
                },
                {
                    "$set": {
                        "lock_id": SCREENING_LOCK_ID,
                        "holder_id": holder_id,
                        "expires_at": expires_at,
                        "updated_at": now,
                    },
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            return False
        return bool(doc and doc.get("holder_id") == holder_id)

    def release_screening_lock(self, holder_id: str) -> None:
        now = _now()
        self.screening_locks.update_one(
            {"lock_id": SCREENING_LOCK_ID, "holder_id": holder_id},
            {
                "$set": {
                    "expires_at": now - timedelta(seconds=1),
                    "updated_at": now,
                }
            },
        )

    def _task_view(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "task_id": task["task_id"],
            "user_id": str(task.get("user_id", "")),
            "symbol": task["symbol"],
            "asset_type": (task.get("asset_type") or "stock").lower(),
            "strategy_key": task["strategy_key"],
            "preset": task.get("preset"),
            "strategy_params": task.get("strategy_params", {}),
            "start_date": task["start_date"],
            "end_date": task["end_date"],
            "initial_cash": task.get("initial_cash", 1000000.0),
            "created_at": task.get("created_at"),
            "lease_token": task.get("lease_token"),
        }
