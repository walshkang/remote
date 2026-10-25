"""Demo module for verifying multi-client sync. Replaced by real modules later."""
from __future__ import annotations

from typing import Any

from app.core.module_base import RemoteModule
from app.core.state_bus import Coalescer


class Module(RemoteModule):
    module_id = "demo"

    def initial_state(self) -> dict[str, Any]:
        return {"level": 40, "applied": 40}

    async def start(self, bus) -> None:
        await super().start(bus)
        # Stand-in for hardware: applies only the latest level every 100ms.
        self._coalescer = Coalescer(self._apply, interval=0.1)

    async def stop(self) -> None:
        await self._coalescer.aclose()

    async def _apply(self, level: int) -> None:
        await self.bus.update(self.module_id, {"applied": level})

    async def handle_action(self, action: str, payload: dict[str, Any], client_id: str) -> None:
        if action == "set":
            level = max(0, min(80, int(payload["value"])))
            await self.bus.update(self.module_id, {"level": level}, origin=client_id)
            self._coalescer.set(level)
        elif action == "delta":
            # Atomic read-modify-write: two simultaneous +1 taps always yield +2.
            async with self.bus.lock(self.module_id):
                level = max(0, min(80, self.bus.get(self.module_id)["level"] + int(payload["delta"])))
                await self.bus.update(self.module_id, {"level": level}, origin=client_id)
            self._coalescer.set(level)
        else:
            await super().handle_action(action, payload, client_id)
