"""In-process patient subscriptions for the single-worker local demo."""

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.connections: dict[int, set[WebSocket]] = {}

    async def connect(self, patient_id: int, websocket: WebSocket):
        await websocket.accept()
        self.connections.setdefault(patient_id, set()).add(websocket)

    def disconnect(self, patient_id: int, websocket: WebSocket):
        connections = self.connections.get(patient_id)
        if connections is not None:
            connections.discard(websocket)
            if not connections:
                self.connections.pop(patient_id, None)

    async def broadcast(self, patient_id: int, message: dict):
        async def send(websocket):
            try:
                await asyncio.wait_for(websocket.send_json(message), timeout=2)
            except Exception:
                # A failed/slow viewer must not turn a committed reading into a 500.
                self.disconnect(patient_id, websocket)
                logger.warning("Removed unavailable WebSocket viewer.")
                try:
                    await asyncio.wait_for(websocket.close(code=1011), timeout=1)
                except Exception:
                    pass  # The underlying connection may already be closed.

        # Snapshot subscriptions because disconnects may occur while sends await.
        await asyncio.gather(*(send(ws) for ws in tuple(self.connections.get(patient_id, ()))))


manager = ConnectionManager()
