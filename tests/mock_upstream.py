"""A faithful in-process mock of the given Hospital Directory API.

Used for integration testing; supports configurable failures so we can test
error scenarios and the resume capability.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class HospitalCreate(BaseModel):
    name: str
    address: str
    phone: Optional[str] = None
    creation_batch_id: Optional[str] = None


def make_mock_upstream() -> FastAPI:
    app = FastAPI(title="Mock Hospital Directory API")
    db: Dict[int, dict] = {}
    state = {"next_id": 1}
    # names that should fail with a 500 (to simulate upstream errors),
    # and how many times they should fail before succeeding (-1 = always)
    fail_names: Dict[str, int] = {}
    app.state.db = db
    app.state.fail_names = fail_names
    app.state.activate_calls: List[str] = []

    @app.post("/hospitals/", status_code=201)
    def create_hospital(payload: HospitalCreate):
        remaining = fail_names.get(payload.name)
        if remaining is not None and remaining != 0:
            if remaining > 0:
                fail_names[payload.name] = remaining - 1
            raise HTTPException(status_code=500, detail="Simulated upstream failure")
        hid = state["next_id"]
        state["next_id"] += 1
        record = {
            "id": hid,
            "name": payload.name,
            "address": payload.address,
            "phone": payload.phone,
            "creation_batch_id": payload.creation_batch_id,
            "active": payload.creation_batch_id is None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        db[hid] = record
        return record

    @app.get("/hospitals/")
    def list_hospitals():
        return list(db.values())

    @app.get("/hospitals/batch/{batch_id}")
    def get_batch(batch_id: str):
        return [h for h in db.values() if h["creation_batch_id"] == batch_id]

    @app.patch("/hospitals/batch/{batch_id}/activate")
    def activate_batch(batch_id: str):
        app.state.activate_calls.append(batch_id)
        found = 0
        for h in db.values():
            if h["creation_batch_id"] == batch_id:
                h["active"] = True
                found += 1
        if not found:
            raise HTTPException(status_code=404, detail="Batch not found")
        return {"batch_id": batch_id, "activated": found}

    @app.delete("/hospitals/batch/{batch_id}", status_code=204)
    def delete_batch(batch_id: str):
        ids = [i for i, h in db.items() if h["creation_batch_id"] == batch_id]
        for i in ids:
            del db[i]
        return None

    return app
