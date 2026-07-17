"""Integration tests: bulk endpoint, validation endpoint, progress, resume,
and error scenarios — all against an in-process mock of the upstream API."""
from .conftest import csv_upload

VALID_CSV = (
    "name,address,phone\n"
    "General Hospital,123 Main St,555-1234\n"
    "City Clinic,9 Oak Ave,555-0000\n"
    "Rural Care,77 Farm Rd,\n"
)


# ---------------------------------------------------------------- bulk create
def test_bulk_create_happy_path(client, upstream):
    resp = client.post("/hospitals/bulk", files=csv_upload(VALID_CSV))
    assert resp.status_code == 201
    body = resp.json()

    assert body["total_hospitals"] == 3
    assert body["processed_hospitals"] == 3
    assert body["failed_hospitals"] == 0
    assert body["batch_activated"] is True
    assert body["status"] == "completed"
    assert body["processing_time_seconds"] >= 0
    assert all(h["status"] == "created_and_activated" for h in body["hospitals"])
    assert all(h["hospital_id"] is not None for h in body["hospitals"])

    # upstream state: created under the batch id and activated
    batch_id = body["batch_id"]
    assert upstream.state.activate_calls == [batch_id]
    records = list(upstream.state.db.values())
    assert len(records) == 3
    assert all(r["creation_batch_id"] == batch_id for r in records)
    assert all(r["active"] is True for r in records)


def test_bulk_create_rejects_invalid_rows_before_hitting_upstream(client, upstream):
    bad = "name,address\n,missing name\n"
    resp = client.post("/hospitals/bulk", files=csv_upload(bad))
    assert resp.status_code == 422
    assert upstream.state.db == {}  # nothing was sent upstream


def test_bulk_create_rejects_oversized_csv(client):
    body = "name,address\n" + "\n".join(f"H{i},{i} St" for i in range(25))
    resp = client.post("/hospitals/bulk", files=csv_upload(body))
    assert resp.status_code == 400
    assert "maximum" in resp.json()["detail"]


def test_bulk_create_rejects_non_csv_filename(client):
    resp = client.post("/hospitals/bulk", files=csv_upload(VALID_CSV, filename="x.xlsx"))
    assert resp.status_code == 400


def test_partial_failure_skips_activation(client, upstream):
    upstream.state.fail_names["City Clinic"] = -1  # always fail
    resp = client.post("/hospitals/bulk", files=csv_upload(VALID_CSV))
    assert resp.status_code == 201
    body = resp.json()

    assert body["failed_hospitals"] == 1
    assert body["processed_hospitals"] == 2
    assert body["batch_activated"] is False
    assert body["status"] == "completed_with_errors"
    assert upstream.state.activate_calls == []  # activation must NOT happen

    failed = [h for h in body["hospitals"] if h["status"] == "failed"]
    assert len(failed) == 1 and failed[0]["name"] == "City Clinic"
    assert failed[0]["error"]


def test_retry_recovers_transient_upstream_error(client, upstream):
    upstream.state.fail_names["City Clinic"] = 1  # fail once, then succeed
    resp = client.post("/hospitals/bulk", files=csv_upload(VALID_CSV))
    body = resp.json()
    assert body["failed_hospitals"] == 0
    assert body["batch_activated"] is True


# ------------------------------------------------------------------ validate
def test_validate_endpoint_reports_errors_without_processing(client, upstream):
    mixed = "name,address,phone\nGood,1 St,555\n,2 St,\n"
    resp = client.post("/hospitals/bulk/validate", files=csv_upload(mixed))
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["total_rows"] == 2
    assert body["valid_rows"] == 1
    assert body["invalid_rows"] == 1
    assert body["errors"][0]["row"] == 2
    assert upstream.state.db == {}


def test_validate_endpoint_ok(client):
    resp = client.post("/hospitals/bulk/validate", files=csv_upload(VALID_CSV))
    body = resp.json()
    assert body["valid"] is True and body["invalid_rows"] == 0
    assert len(body["hospitals_preview"]) == 3


# ------------------------------------------------------------------ progress
def test_progress_polling_after_completion(client):
    batch_id = client.post("/hospitals/bulk", files=csv_upload(VALID_CSV)).json()["batch_id"]
    resp = client.get(f"/batches/{batch_id}/progress")
    assert resp.status_code == 200
    snap = resp.json()
    assert snap["percent_complete"] == 100.0
    assert snap["status"] == "completed"
    assert snap["batch_activated"] is True


def test_progress_unknown_batch_404(client):
    assert client.get("/batches/nope/progress").status_code == 404


def test_websocket_progress_stream(client):
    batch_id = client.post("/hospitals/bulk", files=csv_upload(VALID_CSV)).json()["batch_id"]
    with client.websocket_connect(f"/ws/batches/{batch_id}") as ws:
        msg = ws.receive_json()
        assert msg["batch_id"] == batch_id
        assert msg["status"] == "completed"


def test_list_batches(client):
    b1 = client.post("/hospitals/bulk", files=csv_upload(VALID_CSV)).json()["batch_id"]
    assert b1 in client.get("/batches").json()


# -------------------------------------------------------------------- resume
def test_resume_retries_failed_rows_and_activates(client, upstream):
    upstream.state.fail_names["City Clinic"] = -1
    first = client.post("/hospitals/bulk", files=csv_upload(VALID_CSV)).json()
    assert first["batch_activated"] is False
    batch_id = first["batch_id"]

    # upstream recovers
    upstream.state.fail_names["City Clinic"] = 0

    resumed = client.post(f"/hospitals/bulk/{batch_id}/resume")
    assert resumed.status_code == 200
    body = resumed.json()
    assert body["failed_hospitals"] == 0
    assert body["processed_hospitals"] == 3
    assert body["batch_activated"] is True
    assert body["status"] == "completed"

    # only the failed row was re-sent: 3 hospitals exist, no duplicates
    names = sorted(r["name"] for r in upstream.state.db.values())
    assert names == ["City Clinic", "General Hospital", "Rural Care"]
    assert all(r["active"] for r in upstream.state.db.values())


def test_resume_unknown_batch_404(client):
    assert client.post("/hospitals/bulk/nope/resume").status_code == 404


def test_resume_on_completed_batch_is_noop(client):
    batch_id = client.post("/hospitals/bulk", files=csv_upload(VALID_CSV)).json()["batch_id"]
    resp = client.post(f"/hospitals/bulk/{batch_id}/resume")
    assert resp.status_code == 200
    assert resp.json()["batch_activated"] is True


def test_get_bulk_result_document(client):
    batch_id = client.post("/hospitals/bulk", files=csv_upload(VALID_CSV)).json()["batch_id"]
    resp = client.get(f"/hospitals/bulk/{batch_id}")
    assert resp.status_code == 200
    assert resp.json()["batch_id"] == batch_id
