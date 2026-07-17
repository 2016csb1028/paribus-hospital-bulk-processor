"""Hospital Bulk Processing System — FastAPI entrypoint."""
import logging

from fastapi import FastAPI

from .config import settings
from .routers import bulk, progress

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="Hospital Bulk Processing System",
    description=(
        "Bulk processing layer for the Hospital Directory API. Upload a CSV of "
        "hospitals (max 20 rows), and the system creates them upstream under a "
        "unique batch ID, activates the batch when all rows succeed, and reports "
        "detailed results. Includes CSV validation, live progress tracking "
        "(polling + WebSocket), and resume for failed batches."
    ),
    version="1.0.0",
)

app.include_router(bulk.router)
app.include_router(progress.router)


@app.get("/", tags=["Health"])
async def root() -> dict:
    return {
        "service": "Hospital Bulk Processing System",
        "upstream_api": settings.HOSPITAL_API_BASE_URL,
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def health() -> dict:
    return {"status": "ok"}
