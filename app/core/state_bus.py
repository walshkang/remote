"""Authoritative state, ordering, and hardware-safe command coalescing."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from app.core.ws_manager import WSManager

log = logging.getLogger(__name__)


class StateBus:
    """Single source of truth. All mutations happen on the event loop and are
    serialized per module via a lock, so concurrent clients can't clobber each
    other. Every change gets a monotonically increasing `seq`."""

    def __init__(self, ws: WSManager) -> None:
        self.ws = ws
        self._state: dict[str, dict[str, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._seq = 0

    def register(self, module_id: str, initial: dict[str, Any]) -> None:
        self._state[module_id] = dict(initial)
        self._locks[module_id] = asyncio.Lock()

    def lock(self, module_id: str) -> asyncio.Lock:
        """Hold this around read-modify-write sequences (e.g. volume deltas)."""
        return self._locks[module_id]

    def get(self, module_id: str) -> dict[str, Any]:
        return self._state[module_id]

    def snapshot(self) -> dict[str, Any]:
        return {"type": "snapshot", "seq": self._seq, "state": self._state}

    async def update(self, module_id: str, patch: dict[str, Any], origin: str | None = None) -> None:
        """Merge `patch` into the module's state and broadcast it."""
        self._state[module_id].update(patch)
        self._seq += 1
        await self.ws.broadcast(
            {"type": "state", "module": module_id, "patch": patch, "seq": self._seq, "origin": origin}
        )


class Coalescer:
    """Latest-value-wins sender for rate-limited hardware.

    `set(value)` overwrites any pending value; a worker sends at most one value
    per `interval` seconds, dropping superseded intermediates (slider drags)."""

    def __init__(self, send: Callable[[Any], Awaitable[None]], interval: float) -> None:
        self._send = send
        self._interval = interval
        self._pending: Any = None
        self._has_pending = False
        self._task: asyncio.Task | None = None

    def set(self, value: Any) -> None:
        self._pending = value
        self._has_pending = True
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._drain())

    async def _drain(self) -> None:
        while self._has_pending:
            value, self._has_pending = self._pending, False
            try:
                await self._send(value)
            except Exception:
                log.exception("coalesced send failed")
            await asyncio.sleep(self._interval)

    async def aclose(self) -> None:
        if self._task:
            self._task.cancel()
