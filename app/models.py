"""Pydantic schemas shared across the bulk processing system."""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class RowStatus(str, Enum):
    PENDING = "pending"
    CREATED = "created"                      # created upstream, not yet activated
    CREATED_AND_ACTIVATED = "created_and_activated"
    FAILED = "failed"


class BatchStatus(str, Enum):
    VALIDATING = "validating"
    PROCESSING = "processing"
    ACTIVATING = "activating"
    COMPLETED = "completed"                  # all rows created + batch activated
    COMPLETED_WITH_ERRORS = "completed_with_errors"  # some rows failed, batch NOT activated
    FAILED = "failed"


class HospitalRow(BaseModel):
    """A single parsed CSV row."""
    row: int = Field(..., description="1-based CSV data row number")
    name: str
    address: str
    phone: Optional[str] = None


class HospitalRowResult(BaseModel):
    row: int
    hospital_id: Optional[int] = None
    name: str
    status: RowStatus
    error: Optional[str] = None


class BulkProcessingResult(BaseModel):
    """Response shape mandated by the assignment (plus a couple of useful extras)."""
    batch_id: str
    status: BatchStatus
    total_hospitals: int
    processed_hospitals: int
    failed_hospitals: int
    processing_time_seconds: float
    batch_activated: bool
    hospitals: List[HospitalRowResult]


class RowValidationError(BaseModel):
    row: int
    errors: List[str]


class CSVValidationResult(BaseModel):
    valid: bool
    total_rows: int
    valid_rows: int
    invalid_rows: int
    errors: List[RowValidationError]
    hospitals_preview: List[HospitalRow]


class ProgressSnapshot(BaseModel):
    """Snapshot returned by the polling endpoint and pushed over WebSocket."""
    batch_id: str
    status: BatchStatus
    total_hospitals: int
    processed_hospitals: int
    failed_hospitals: int
    percent_complete: float
    batch_activated: bool
    elapsed_seconds: float
