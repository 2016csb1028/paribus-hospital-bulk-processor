"""Bulk processing orchestration.

Workflow (per assignment):
  1. CSV already validated + parsed by the router.
  2. Generate unique batch ID (done by router).
  3. POST /hospitals/ for each row, tagged with the batch ID (concurrently,
     bounded by a semaphore — this is the main performance optimisation).
  4. If, and only if, ALL hospitals were created successfully, PATCH
     /hospitals/batch/{batch_id}/activate.
  5. Return comprehensive processing results.

Resume: failed rows are kept in the in-memory store; a resume call retries
only the failed/pending rows and then attempts activation again.
"""
from __future__ import annotations

import asyncio
import logging

from .batch_store import BatchState
from .config import settings
from .hospital_client import HospitalAPIError, HospitalDirectoryClient
from .models import BatchStatus, BulkProcessingResult, HospitalRow, RowStatus

logger = logging.getLogger(__name__)


async def _create_one(
    client: HospitalDirectoryClient,
    state: BatchState,
    row: HospitalRow,
    sem: asyncio.Semaphore,
) -> None:
    result = state.results[row.row]
    async with sem:
        try:
            created = await client.create_hospital(
                name=row.name, address=row.address, phone=row.phone, batch_id=state.batch_id
            )
            result.hospital_id = created.get("id")
            result.status = RowStatus.CREATED
            result.error = None
        except HospitalAPIError as exc:
            logger.error("Row %d (%s) failed: %s", row.row, row.name, exc)
            result.status = RowStatus.FAILED
            result.error = str(exc)
        finally:
            state.publish()


async def process_batch(
    state: BatchState, client: HospitalDirectoryClient, rows_to_process=None
) -> BulkProcessingResult:
    """Create hospitals (concurrently) and activate the batch when fully successful."""
    rows = rows_to_process if rows_to_process is not None else state.rows
    sem = asyncio.Semaphore(settings.CONCURRENCY)

    state.status = BatchStatus.PROCESSING
    state.publish()

    await asyncio.gather(*(_create_one(client, state, row, sem) for row in rows))

    if state.failed == 0:
        state.status = BatchStatus.ACTIVATING
        state.publish()
        try:
            await client.activate_batch(state.batch_id)
            state.batch_activated = True
            for r in state.results.values():
                if r.status == RowStatus.CREATED:
                    r.status = RowStatus.CREATED_AND_ACTIVATED
            state.finish(BatchStatus.COMPLETED)
        except HospitalAPIError as exc:
            logger.error("Activation of batch %s failed: %s", state.batch_id, exc)
            state.finish(BatchStatus.COMPLETED_WITH_ERRORS)
    else:
        # Assignment: activate only "once all hospitals are created successfully".
        state.finish(BatchStatus.COMPLETED_WITH_ERRORS)

    return build_result(state)


async def resume_batch(state: BatchState, client: HospitalDirectoryClient) -> BulkProcessingResult:
    """Retry only rows that failed (or never ran), then re-attempt activation."""
    retry_rows = [
        row for row in state.rows
        if state.results[row.row].status in (RowStatus.FAILED, RowStatus.PENDING)
    ]
    for row in retry_rows:
        res = state.results[row.row]
        res.status = RowStatus.PENDING
        res.error = None

    if not retry_rows and state.batch_activated:
        return build_result(state)  # nothing to do

    # Reset the clock so processing_time reflects the resume run
    import time
    state.started_at = time.monotonic()
    state.finished_at = None

    return await process_batch(state, client, rows_to_process=retry_rows)


def build_result(state: BatchState) -> BulkProcessingResult:
    return BulkProcessingResult(
        batch_id=state.batch_id,
        status=state.status,
        total_hospitals=state.total,
        processed_hospitals=state.processed,
        failed_hospitals=state.failed,
        processing_time_seconds=state.elapsed_seconds,
        batch_activated=state.batch_activated,
        hospitals=sorted(state.results.values(), key=lambda r: r.row),
    )
