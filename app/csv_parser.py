"""CSV parsing & validation.

Expected format (header required):  name,address,phone   (phone optional)
"""
from __future__ import annotations

import csv
import io
import re
from typing import List, Tuple

from .config import settings
from .models import HospitalRow, RowValidationError

REQUIRED_COLUMNS = {"name", "address"}
ALLOWED_COLUMNS = {"name", "address", "phone"}
PHONE_RE = re.compile(r"^[0-9+\-().\sx]{3,25}$")


class CSVFormatError(Exception):
    """Raised when the file as a whole is unusable (not per-row errors)."""


def decode_upload(raw: bytes) -> str:
    if not raw or not raw.strip():
        raise CSVFormatError("Uploaded file is empty.")
    if len(raw) > settings.MAX_UPLOAD_BYTES:
        raise CSVFormatError("Uploaded file is too large.")
    try:
        return raw.decode("utf-8-sig")  # tolerate BOM from Excel exports
    except UnicodeDecodeError:
        raise CSVFormatError("File is not valid UTF-8 encoded CSV.")


def parse_and_validate(raw: bytes) -> Tuple[List[HospitalRow], List[RowValidationError]]:
    """Parse CSV bytes into rows + per-row validation errors.

    Raises CSVFormatError for file-level problems (bad header, too many rows, ...).
    """
    text = decode_upload(raw)
    reader = csv.DictReader(io.StringIO(text))

    if reader.fieldnames is None:
        raise CSVFormatError("CSV has no header row.")

    header = [h.strip().lower() for h in reader.fieldnames]
    missing = REQUIRED_COLUMNS - set(header)
    if missing:
        raise CSVFormatError(
            f"CSV header must contain columns: name,address[,phone]. Missing: {', '.join(sorted(missing))}"
        )
    unknown = set(header) - ALLOWED_COLUMNS
    if unknown:
        raise CSVFormatError(f"Unknown CSV columns: {', '.join(sorted(unknown))}")

    rows: List[HospitalRow] = []
    errors: List[RowValidationError] = []

    for i, record in enumerate(reader, start=1):
        # normalise keys (DictReader keeps original header casing)
        rec = { (k.strip().lower() if k else k): (v.strip() if isinstance(v, str) else v)
                for k, v in record.items() }

        row_errors: List[str] = []
        name = rec.get("name") or ""
        address = rec.get("address") or ""
        phone = rec.get("phone") or None

        if not name:
            row_errors.append("name is required")
        elif len(name) > 200:
            row_errors.append("name exceeds 200 characters")

        if not address:
            row_errors.append("address is required")
        elif len(address) > 300:
            row_errors.append("address exceeds 300 characters")

        if phone and not PHONE_RE.match(phone):
            row_errors.append("phone has an invalid format")

        # Extra unnamed columns show up under None key
        if None in record and any(v for v in (record[None] or [])):
            row_errors.append("row has more columns than the header")

        if row_errors:
            errors.append(RowValidationError(row=i, errors=row_errors))
        else:
            rows.append(HospitalRow(row=i, name=name, address=address, phone=phone))

    total = len(rows) + len(errors)
    if total == 0:
        raise CSVFormatError("CSV contains a header but no data rows.")
    if total > settings.MAX_CSV_ROWS:
        raise CSVFormatError(
            f"CSV contains {total} hospitals; the maximum allowed is {settings.MAX_CSV_ROWS}."
        )

    return rows, errors
