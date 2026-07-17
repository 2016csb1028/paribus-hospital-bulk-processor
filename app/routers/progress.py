"""Progress tracking: polling endpoint + WebSocket push updates."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ..batch_store import batch_store
from ..models import BatchStatus, ProgressSnapshot

router = APIRouter(tags=["Progress Tracking"])

TERMINAL = {BatchStatus.COMPLETED, BatchStatus.COMPLETED_WITH_ERRORS, BatchStatus.FAILED}


@router.get("/batches/{batch_id}/progress", response_model=ProgressSnapshot)
async def get_progress(batch_id: str) -> ProgressSnapshot:
    """Polling endpoint: current progress of a bulk operation."""
    state = batch_store.get(batch_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown batch_id.")
    return state.snapshot()


@router.get("/batches", response_model=list[str])
async def list_batches() -> list[str]:
    """List all batch IDs known to this instance."""
    return batch_store.all_ids()


@router.websocket("/ws/batches/{batch_id}")
async def progress_websocket(websocket: WebSocket, batch_id: str) -> None:
    """Real-time progress updates. Sends a snapshot immediately, then a message
    per row completion, and closes after the batch reaches a terminal state."""
    await websocket.accept()
    state = batch_store.get(batch_id)
    if state is None:
        await websocket.send_json({"error": "Unknown batch_id."})
        await websocket.close(code=4404)
        return

    queue = state.subscribe()
    try:
        snap = state.snapshot()
        await websocket.send_json(snap.model_dump(mode="json"))
        if snap.status in TERMINAL:
            return
        while True:
            try:
                snap = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                snap = state.snapshot()  # heartbeat
            await websocket.send_json(snap.model_dump(mode="json"))
            if snap.status in TERMINAL:
                break
    except WebSocketDisconnect:
        pass
    finally:
        state.unsubscribe(queue)
        try:
            await websocket.close()
        except RuntimeError:
            pass
