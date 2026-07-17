# Hospital Bulk Processing System

A FastAPI service that bulk-loads hospitals into the (given) **Hospital Directory API** from a CSV upload. It creates every hospital under a unique batch ID, activates the batch once **all** rows succeed, and returns a comprehensive result document. It also ships every optional task from the assignment: performance optimization, real-time progress tracking (WebSocket + polling), resume capability, a CSV validation endpoint, a full test suite, and Dockerization.

## Architecture

```
                ┌──────────────────────────────────────────────┐
   CSV upload   │        Hospital Bulk Processing System        │
  ────────────▶ │                                              │
                │  routers/bulk.py      routers/progress.py    │
                │       │                   ▲    ▲             │
                │       ▼                   │    │ (pub/sub)   │
                │  csv_parser.py       batch_store.py          │
                │       │                   ▲                  │
                │       ▼                   │                  │
                │  processor.py ────────────┘                  │
                │       │  (bounded-concurrency orchestration) │
                │       ▼                                      │
                │  hospital_client.py (httpx, retries+backoff) │
                └───────┬──────────────────────────────────────┘
                        │  POST /hospitals/  (×N, concurrent)
                        │  PATCH /hospitals/batch/{id}/activate
                        ▼
              Hospital Directory API (given, on Render)
```

**Design decisions**

- **Async, bounded concurrency.** Rows are created upstream concurrently through `asyncio.gather` with a semaphore (`BULK_CONCURRENCY`, default 10). For a Render-hosted upstream where a single create can take seconds, this turns O(N) sequential latency into roughly O(N / concurrency).
- **Retries with exponential backoff.** The upstream lives on a free-tier host that can cold-start or return transient 5xx/429; each create/activate call is retried up to `MAX_RETRIES` times with exponential backoff before being marked failed.
- **All-or-nothing activation.** Per the spec, `PATCH /hospitals/batch/{batch_id}/activate` is called only when *every* row was created successfully. Partial batches stay inactive (`status: completed_with_errors`) and can be **resumed**.
- **In-memory batch store** (per the assignment's constraints) keeps per-row state, powers the polling/WebSocket progress endpoints, and enables resume. A `BatchState` publishes a snapshot to subscribers after every row completes.
- **Clean layering.** Parsing/validation, upstream client, orchestration, and HTTP layer are independent modules — each unit-testable in isolation.

## API

Interactive docs: **`/docs`** (Swagger UI) once running.

| Method | Path | Description |
|---|---|---|
| `POST` | `/hospitals/bulk` | Upload CSV (multipart, field `file`), process the batch, return full results |
| `POST` | `/hospitals/bulk/validate` | Dry-run CSV validation — nothing is sent upstream |
| `POST` | `/hospitals/bulk/{batch_id}/resume` | Retry only the failed rows of a batch, then re-attempt activation |
| `GET` | `/hospitals/bulk/{batch_id}` | Full result document for a batch |
| `GET` | `/batches/{batch_id}/progress` | Progress snapshot (polling) |
| `GET` | `/batches` | List known batch IDs |
| `WS` | `/ws/batches/{batch_id}` | Real-time progress pushed per row completion |
| `GET` | `/health` | Health check |

### CSV format

Header required; `phone` optional; **max 20 rows** (assignment constraint).

```csv
name,address,phone
General Hospital,123 Main St,555-1234
City Clinic,9 Oak Ave,
```

### Example

```bash
curl -X POST https://<your-app>.onrender.com/hospitals/bulk \
     -F "file=@sample_data/hospitals_valid.csv"
```

```json
{
  "batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "total_hospitals": 5,
  "processed_hospitals": 5,
  "failed_hospitals": 0,
  "processing_time_seconds": 3.42,
  "batch_activated": true,
  "hospitals": [
    { "row": 1, "hospital_id": 101, "name": "General Hospital",
      "status": "created_and_activated", "error": null }
  ]
}
```

Error handling: file-level problems (bad header, >20 rows, wrong encoding) return `400`; per-row validation failures return `422` with row numbers and reasons; upstream failures are reported per row with `status: "failed"` and an `error` message, and the batch is left inactive so it can be resumed.

## Running locally

```bash
pip install -r requirements.txt
export HOSPITAL_API_BASE_URL=https://hospital-directory.onrender.com
uvicorn app.main:app --reload
# → http://localhost:8000/docs
```

### Docker

```bash
docker compose up --build
# → http://localhost:8000/docs
```

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `HOSPITAL_API_BASE_URL` | `https://hospital-directory.onrender.com` | Upstream Hospital Directory API |
| `BULK_CONCURRENCY` | `10` | Max concurrent upstream create calls |
| `MAX_RETRIES` | `3` | Retries per upstream call (exp. backoff) |
| `REQUEST_TIMEOUT_SECONDS` | `30` | Per-request timeout |
| `MAX_CSV_ROWS` | `20` | Row limit (assignment constraint) |

## Testing

27 tests: unit tests for the CSV parser and full integration tests that run the service against an in-process mock of the Hospital Directory API (`tests/mock_upstream.py`), covering the happy path, per-row validation, the 20-row limit, transient-failure retries, partial failures skipping activation, progress polling, the WebSocket stream, and resume.

```bash
pip install -r requirements-dev.txt
pytest -v
```

## Deployment (Render)

1. Push this repo to GitHub.
2. On Render: **New → Blueprint**, point it at the repo — `render.yaml` configures everything (build command, start command, env vars).
   Or manually: **New → Web Service**, build `pip install -r requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. Note: batch state is in-memory (per the assignment), so progress/resume state resets on redeploys and doesn't survive across multiple instances.

## Project structure

```
app/
├── main.py              # FastAPI app + health endpoints
├── config.py            # Env-driven settings
├── models.py            # Pydantic schemas & status enums
├── csv_parser.py        # CSV parsing + validation
├── hospital_client.py   # Async upstream client (retries/backoff)
├── batch_store.py       # In-memory batch state + progress pub/sub
├── processor.py         # Bulk orchestration + resume logic
└── routers/
    ├── bulk.py          # /hospitals/bulk endpoints
    └── progress.py      # polling + WebSocket progress
tests/                   # pytest suite + mock upstream API
sample_data/             # example CSVs (valid & invalid)
Dockerfile, docker-compose.yml, render.yaml
```
