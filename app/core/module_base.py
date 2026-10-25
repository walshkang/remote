"""Base contract every integration (Denon, Hue, ...) implements."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.core.state_bus import StateBus


class RemoteModule:
    """A self-contained integration. Subclass and drop into app/modules/<id>/."""

    #: Unique namespace, also the key in the state snapshot sent to clients.
    module_id: str = "base"

    def __init__(self) -> None:
        self.bus: "StateBus | None" = None

    def initial_state(self) -> dict[str, Any]:
        """State slice shown before the first update arrives."""
        return {}

    async def start(self, bus: "StateBus") -> None:
        """Called once at startup. Start background tasks here; must not block."""
        self.bus = bus

    async def stop(self) -> None:
        """Called at shutdown. Cancel background tasks / close connections."""

    async def handle_action(self, action: str, payload: dict[str, Any], client_id: str) -> None:
        """Handle a client command. Publish results via self.bus.update()."""
        raise NotImplementedError(f"{self.module_id}: unknown action {action!r}")
