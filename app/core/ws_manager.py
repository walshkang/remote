"""Tracks connected WebSocket clients and broadcasts messages to them."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)


class WSManager:
    def __init__(self) -> None:
        self._clients: dict[str, WebSocket] = {}

    async def connect(self, client_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._clients[client_id] = ws

    def disconnect(self, client_id: str) -> None:
        self._clients.pop(client_id, None)

    async def send(self, client_id: str, message: dict[str, Any]) -> None:
        ws = self._clients.get(client_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(client_id)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send to everyone; a slow/dead client never blocks the others."""
        if not self._clients:
            return
        results = await asyncio.gather(
            *(ws.send_json(message) for ws in self._clients.values()),
            return_exceptions=True,
        )
        for cid, result in zip(list(self._clients), results):
            if isinstance(result, Exception):
                log.debug("dropping client %s: %s", cid, result)
                self.disconnect(cid)
