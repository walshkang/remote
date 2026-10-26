"""Denon AVR-X1200W Module for Remote."""
from __future__ import annotations

import logging
import os
from typing import Any

from app.core.module_base import RemoteModule
from app.core.state_bus import Coalescer
from app.modules.denon.driver import DenonDriver

log = logging.getLogger(__name__)


class Module(RemoteModule):
    module_id = "denon"

    def __init__(self) -> None:
        super().__init__()
        raw_host = os.getenv("DENON_HOST", "192.168.1.226").strip()
        self.telnet_port = int(os.getenv("DENON_TELNET_PORT", "23"))
        self.http_port = int(os.getenv("DENON_HTTP_PORT", "80"))
        if ":" in raw_host:
            parts = raw_host.split(":")
            self.host = parts[0]
            self.telnet_port = int(parts[1])
        else:
            self.host = raw_host
        self.driver: DenonDriver | None = None
        self._coalescer: Coalescer | None = None

    def initial_state(self) -> dict[str, Any]:
        return {
            "configured": bool(self.host),
            "host": self.host,
            "connected": False,
            "power": "UNKNOWN",
            "volume": 50.0,
            "volume_db": "-30.0 dB",
            "mute": False,
            "source": "UNKNOWN",
            "sources": [
                {"code": "MPLAY", "name": "Turntable", "icon": "🎛️"},
                {"code": "TV", "name": "TV Audio", "icon": "🔊"},
                {"code": "SAT/CBL", "name": "CD Player", "icon": "💿"},
                {"code": "BT", "name": "Bluetooth", "icon": "ᛒ"},
                {"code": "NET", "name": "Online Music", "icon": "🌐"},
                {"code": "AUX1", "name": "Front AUX", "icon": "🔌"},
            ],
            "zone_name": "LIVING RM",
            "now_playing": {
                "track": "",
                "artist": "",
                "album": ""
            }
        }

    async def start(self, bus) -> None:
        await super().start(bus)
        self._coalescer = Coalescer(self._send_hardware_volume, interval=0.1)

        if self.host:
            await self._init_driver(self.host)

    async def _init_driver(self, host: str) -> None:
        if ":" in host:
            parts = host.split(":")
            self.host = parts[0]
            self.telnet_port = int(parts[1])
        else:
            self.host = host

        if self.driver:
            await self.driver.stop()

        self.driver = DenonDriver(
            self.host,
            telnet_port=self.telnet_port,
            http_port=self.http_port,
            on_state_change=self._on_driver_state,
        )
        await self.driver.start()
        await self.bus.update(self.module_id, {"configured": True, "host": self.host})

    async def stop(self) -> None:
        if self._coalescer:
            await self._coalescer.aclose()
        if self.driver:
            await self.driver.stop()

    async def _on_driver_state(self, patch: dict[str, Any]) -> None:
        await self.bus.update(self.module_id, patch)

    async def _send_hardware_volume(self, val: float) -> None:
        if not self.driver:
            return
        # Denon volume string: '50' for 50.0, '505' for 50.5
        int_part = int(val)
        frac_part = int(round((val - int_part) * 10))
        if frac_part == 5:
            cmd = f"MV{int_part:02d}5"
        else:
            cmd = f"MV{int_part:02d}"
        await self.driver.send_raw(cmd)

    async def handle_action(self, action: str, payload: dict[str, Any], client_id: str) -> None:
        # Configuration action
        if action == "set_host":
            new_host = str(payload.get("host", "")).strip()
            if new_host:
                await self._init_driver(new_host)
            return

        if action == "power_toggle":
            current = self.bus.get(self.module_id).get("power")
            new_power = "STANDBY" if current == "ON" else "ON"
            await self.bus.update(self.module_id, {"power": new_power}, origin=client_id)
            if self.driver:
                cmd = "PWSTANDBY" if current == "ON" else "PWON"
                await self.driver.send_raw(cmd)

        elif action == "mute_toggle":
            current_mute = self.bus.get(self.module_id).get("mute", False)
            new_mute = not current_mute
            await self.bus.update(self.module_id, {"mute": new_mute}, origin=client_id)
            if self.driver:
                cmd = "MUOFF" if current_mute else "MUON"
                await self.driver.send_raw(cmd)

        elif action == "volume_set":
            val = max(0.0, min(80.0, float(payload.get("value", 35.0))))
            rel_db = val - 80.0
            db_display = f"{rel_db:+.1f} dB" if rel_db != 0 else "0.0 dB"
            await self.bus.update(
                self.module_id,
                {"volume": val, "volume_db": db_display},
                origin=client_id
            )
            if self._coalescer and self.driver:
                self._coalescer.set(val)

        elif action == "volume_delta":
            delta = float(payload.get("delta", 0.0))
            async with self.bus.lock(self.module_id):
                curr = float(self.bus.get(self.module_id).get("volume", 35.0))
                val = max(0.0, min(80.0, curr + delta))
                rel_db = val - 80.0
                db_display = f"{rel_db:+.1f} dB" if rel_db != 0 else "0.0 dB"
                await self.bus.update(
                    self.module_id,
                    {"volume": val, "volume_db": db_display},
                    origin=client_id
                )
            if self._coalescer and self.driver:
                self._coalescer.set(val)

        elif action == "set_source":
            source = str(payload.get("source", "")).strip()
            if source:
                await self.bus.update(self.module_id, {"source": source}, origin=client_id)
                if self.driver:
                    await self.driver.send_raw(f"SI{source}")
