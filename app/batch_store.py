"""In-memory batch state store.

Holds live/finished batch state so that:
  * the polling endpoint can report progress,
  * WebSocket subscribers receive push updates,
  * failed batches can be resumed.

Persistence is in-memory per the assignment's technical constraints.
"""
from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional

from .models import (
    BatchStatus,
    HospitalRow,
    HospitalRowResult,
    ProgressSnapshot,
    RowStatus,
)


class BatchState:
    def __init__(self, batch_id: str, rows: List[HospitalRow]):
        self.batch_id = batch_id
        self.status = BatchStatus.PROCESSING
        self.rows: List[HospitalRow] = rows
        self.results: Dict[int, HospitalRowResult] = {
            r.row: HospitalRowResult(row=r.row, name=r.name, status=RowStatus.PENDING)
            for r in rows
        }
        self.batch_activated = False
        self.started_at = time.monotonic()
        self.finished_at: Optional[float] = None
        self._subscribers: List[asyncio.Queue] = []

    # ---- derived counters -------------------------------------------------
    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def processed(self) -> int:
        done = (RowStatus.CREATED, RowStatus.CREATED_AND_ACTIVATED)
        return sum(1 for r in self.results.values() if r.status in done)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results.values() if r.status == RowStatus.FAILED)

    @property
    def elapsed_seconds(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return round(end - self.started_at, 3)

    def snapshot(self) -> ProgressSnapshot:
        attempted = self.processed + self.failed
        pct = round(100.0 * attempted / self.total, 1) if self.total else 100.0
        return ProgressSnapshot(
            batch_id=self.batch_id,
            status=self.status,
            total_hospitals=self.total,
            processed_hospitals=self.processed,
            failed_hospitals=self.failed,
            percent_complete=pct,
            batch_activated=self.batch_activated,
            elapsed_seconds=self.elapsed_seconds,
        )

    # ---- pub/sub for WebSocket progress ------------------------------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def publish(self) -> None:
        snap = self.snapshot()
        for q in list(self._subscribers):
            q.put_nowait(snap)

    def finish(self, status: BatchStatus) -> None:
        self.status = status
        self.finished_at = time.monotonic()
        self.publish()


class BatchStore:
    def __init__(self) -> None:
        self._batches: Dict[str, BatchState] = {}
        self._lock = asyncio.Lock()

    async def create(self, batch_id: str, rows: List[HospitalRow]) -> BatchState:
        async with self._lock:
            state = BatchState(batch_id, rows)
            self._batches[batch_id] = state
            return state

    def get(self, batch_id: str) -> Optional[BatchState]:
        return self._batches.get(batch_id)

    def all_ids(self) -> List[str]:
        return list(self._batches.keys())


# Module-level singleton (in-memory persistence per assignment constraints)
batch_store = BatchStore()
