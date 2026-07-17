"""Shared pytest fixtures.

The bulk processor's outbound client is rewired to an in-process mock of the
Hospital Directory API via httpx's ASGITransport — full integration tests with
no network access required.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.batch_store import batch_store
from app.config import settings
from app.hospital_client import HospitalDirectoryClient
from app.main import app

from .mock_upstream import make_mock_upstream


@pytest.fixture()
def upstream():
    return make_mock_upstream()


@pytest.fixture()
def client(upstream, monkeypatch):
    # Speed up retry behaviour in tests
    monkeypatch.setattr(settings, "MAX_RETRIES", 1)
    monkeypatch.setattr(settings, "RETRY_BACKOFF_BASE_SECONDS", 0.01)

    transport = httpx.ASGITransport(app=upstream)

    def factory(base_url=None, client=None):  # noqa: ARG001
        return HospitalDirectoryClient(
            base_url="http://upstream",
            client=httpx.AsyncClient(transport=transport, base_url="http://upstream"),
        )

    monkeypatch.setattr("app.routers.bulk.HospitalDirectoryClient", factory)

    # Fresh in-memory store per test
    batch_store._batches.clear()

    with TestClient(app) as tc:
        yield tc


def csv_upload(content: str, filename: str = "hospitals.csv"):
    return {"file": (filename, content.encode(), "text/csv")}
