"""Bulk processing endpoints: upload, validate, resume."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..batch_store import batch_store
from ..csv_parser import CSVFormatError, parse_and_validate
from ..hospital_client import HospitalDirectoryClient
from ..models import BatchStatus, BulkProcessingResult, CSVValidationResult
from ..processor import build_result, process_batch, resume_batch

router = APIRouter(prefix="/hospitals", tags=["Bulk Processing"])


async def _read_csv_upload(file: UploadFile) -> bytes:
    if file.filename and not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file.")
    return await file.read()


@router.post("/bulk", response_model=BulkProcessingResult, status_code=201)
async def bulk_create_hospitals(file: UploadFile = File(...)) -> BulkProcessingResult:
    """Upload a CSV (`name,address,phone` — phone optional, max 20 rows).

    Creates every hospital in the upstream Hospital Directory API under a fresh
    batch ID, then activates the batch once **all** rows succeed. Progress can be
    followed live at `GET /batches/{batch_id}/progress` or `WS /ws/batches/{batch_id}`.
    """
    raw = await _read_csv_upload(file)
    try:
        rows, row_errors = parse_and_validate(raw)
    except CSVFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if row_errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "CSV contains invalid rows. Fix them or use POST /hospitals/bulk/validate to inspect.",
                "errors": [e.model_dump() for e in row_errors],
            },
        )

    batch_id = str(uuid.uuid4())
    state = await batch_store.create(batch_id, rows)

    client = HospitalDirectoryClient()
    try:
        result = await process_batch(state, client)
    finally:
        await client.aclose()
    return result


@router.post("/bulk/validate", response_model=CSVValidationResult)
async def validate_csv(file: UploadFile = File(...)) -> CSVValidationResult:
    """Dry-run validation of a CSV file — nothing is sent upstream."""
    raw = await _read_csv_upload(file)
    try:
        rows, row_errors = parse_and_validate(raw)
    except CSVFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return CSVValidationResult(
        valid=not row_errors,
        total_rows=len(rows) + len(row_errors),
        valid_rows=len(rows),
        invalid_rows=len(row_errors),
        errors=row_errors,
        hospitals_preview=rows,
    )


@router.post("/bulk/{batch_id}/resume", response_model=BulkProcessingResult)
async def resume_bulk_operation(batch_id: str) -> BulkProcessingResult:
    """Resume a batch that completed with errors: retries only failed rows,
    then re-attempts batch activation."""
    state = batch_store.get(batch_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown batch_id.")
    if state.status in (BatchStatus.PROCESSING, BatchStatus.ACTIVATING):
        raise HTTPException(status_code=409, detail="Batch is still being processed.")
    if state.status == BatchStatus.COMPLETED and state.batch_activated:
        return build_result(state)

    client = HospitalDirectoryClient()
    try:
        result = await resume_batch(state, client)
    finally:
        await client.aclose()
    return result


@router.get("/bulk/{batch_id}", response_model=BulkProcessingResult)
async def get_bulk_result(batch_id: str) -> BulkProcessingResult:
    """Fetch the full (current) result document for a batch."""
    state = batch_store.get(batch_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown batch_id.")
    return build_result(state)
