"""Async client for the (given) Hospital Directory API.

Adds bounded retries with exponential backoff for transient failures — important
because the upstream lives on Render's free tier and may cold-start or hiccup.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from .config import settings

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class HospitalAPIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class HospitalDirectoryClient:
    """Thin async wrapper around the upstream API."""

    def __init__(self, base_url: Optional[str] = None, client: Optional[httpx.AsyncClient] = None):
        self.base_url = (base_url or settings.HOSPITAL_API_BASE_URL).rstrip("/")
        self._external_client = client is not None
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=settings.REQUEST_TIMEOUT_SECONDS,
            limits=httpx.Limits(max_connections=settings.CONCURRENCY * 2),
        )

    async def aclose(self) -> None:
        if not self._external_client:
            await self._client.aclose()

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(settings.MAX_RETRIES + 1):
            try:
                resp = await self._client.request(method, url, **kwargs)
                if resp.status_code in RETRYABLE_STATUS and attempt < settings.MAX_RETRIES:
                    raise HospitalAPIError(
                        f"Upstream returned {resp.status_code}", resp.status_code
                    )
                return resp
            except (httpx.TransportError, HospitalAPIError) as exc:
                last_exc = exc
                if attempt < settings.MAX_RETRIES:
                    delay = settings.RETRY_BACKOFF_BASE_SECONDS * (2 ** attempt)
                    logger.warning(
                        "Retrying %s %s (attempt %d/%d) after error: %s",
                        method, url, attempt + 1, settings.MAX_RETRIES, exc,
                    )
                    await asyncio.sleep(delay)
        raise HospitalAPIError(f"Request failed after retries: {last_exc}")

    async def create_hospital(
        self, name: str, address: str, phone: Optional[str], batch_id: str
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": name,
            "address": address,
            "creation_batch_id": batch_id,
        }
        if phone:
            payload["phone"] = phone
        resp = await self._request("POST", "/hospitals/", json=payload)
        if resp.status_code not in (200, 201):
            raise HospitalAPIError(
                f"Create hospital failed ({resp.status_code}): {resp.text[:200]}",
                resp.status_code,
            )
        return resp.json()

    async def activate_batch(self, batch_id: str) -> Dict[str, Any]:
        resp = await self._request("PATCH", f"/hospitals/batch/{batch_id}/activate")
        if resp.status_code not in (200, 204):
            raise HospitalAPIError(
                f"Batch activation failed ({resp.status_code}): {resp.text[:200]}",
                resp.status_code,
            )
        return resp.json() if resp.content else {}

    async def get_batch(self, batch_id: str) -> List[Dict[str, Any]]:
        resp = await self._request("GET", f"/hospitals/batch/{batch_id}")
        if resp.status_code != 200:
            raise HospitalAPIError(
                f"Get batch failed ({resp.status_code})", resp.status_code
            )
        return resp.json()

    async def delete_batch(self, batch_id: str) -> None:
        resp = await self._request("DELETE", f"/hospitals/batch/{batch_id}")
        if resp.status_code not in (200, 204):
            raise HospitalAPIError(
                f"Delete batch failed ({resp.status_code})", resp.status_code
            )
