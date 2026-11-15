"""Petlibro Granary Feeder module: tank status, portions fed, and hold-to-dispense snack."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from app.core.module_base import RemoteModule
from app.modules.petlibro.driver import PetlibroAuthError, PetlibroDriver

log = logging.getLogger(__name__)

DATA_FILE = Path(__file__).resolve().parents[3] / "data" / "petlibro.json"
FEED_COOLDOWN_S = 60
POLL_INTERVAL_S = 300


def _load_saved() -> dict[str, Any]:
    try:
        if DATA_FILE.exists():
            data = json.loads(DATA_FILE.read_text())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_data(data: dict[str, Any]) -> None:
    DATA_FILE.parent.mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, indent=2))
    try:
        DATA_FILE.chmod(0o600)
    except Exception:
        pass


class Module(RemoteModule):
    module_id = "petlibro"

    def __init__(self) -> None:
        super().__init__()
        saved = _load_saved()
        self.email = os.getenv("PETLIBRO_EMAIL", "").strip() or saved.get("email", "").strip()
        self.password = os.getenv("PETLIBRO_PASSWORD", "")
        self.token = os.getenv("PETLIBRO_TOKEN", "").strip() or saved.get("token", "").strip()
        self.guest_pin = os.getenv("GUEST_PIN", "").strip()
        self.feeder: dict[str, Any] | None = saved.get("feeder")

        self.driver: PetlibroDriver | None = None
        self._task: asyncio.Task | None = None
        self._last_feed = 0.0

    def _is_configured(self) -> bool:
        return bool(self.token or (self.email and self.password))

    def initial_state(self) -> dict[str, Any]:
        return {
            "configured": self._is_configured(),
            "connected": False,
            "pin_required": bool(self.guest_pin),
            "error": "",
            "notice": "",
            "feeder": self.feeder,
        }

    async def start(self, bus) -> None:
        await super().start(bus)
        self.driver = PetlibroDriver(
            email=self.email,
            password=self.password,
            token=self.token,
        )
        if self._is_configured():
            self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self.driver:
            await self.driver.aclose()

    def _persist(self) -> None:
        _save_data(
            {
                "email": self.email,
                "token": self.token,
                "feeder": self.feeder,
            }
        )

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.refresh_feeder()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("Petlibro poll error: %s", e)
            await asyncio.sleep(POLL_INTERVAL_S)

    async def refresh_feeder(self) -> dict[str, Any]:
        if not self.driver:
            self.driver = PetlibroDriver(email=self.email, password=self.password, token=self.token)

        try:
            snap = await self.driver.fetch_feeder_snapshot()
            self.token = self.driver.token
            self.feeder = snap
            self._persist()
            await self.bus.update(
                self.module_id,
                {
                    "configured": True,
                    "connected": True,
                    "error": "",
                    "feeder": snap,
                },
            )
            return snap
        except PetlibroAuthError as e:
            await self.bus.update(self.module_id, {"connected": False, "error": str(e)})
            raise
        except Exception as e:
            await self.bus.update(
                self.module_id,
                {"connected": False, "error": f"Petlibro offline: {e}"},
            )
            raise

    async def _notice(self, text: str) -> None:
        await self.bus.update(self.module_id, {"notice": text})

        async def clear() -> None:
            await asyncio.sleep(5)
            if self.bus and self.bus.get(self.module_id).get("notice") == text:
                await self.bus.update(self.module_id, {"notice": ""})

        asyncio.create_task(clear())

    async def handle_action(self, action: str, payload: dict[str, Any], client_id: str) -> None:
        if action == "set_credentials":
            email = str(payload.get("email", "")).strip()
            password = str(payload.get("password", ""))
            token = str(payload.get("token", "")).strip()
            if not token and not (email and password):
                await self._notice("Enter Petlibro email & password, or a session token")
                return
            if email:
                self.email = email
            if password:
                self.password = password
            if token:
                self.token = token
            if self.driver:
                self.driver.email = self.email
                self.driver.password = self.password
                self.driver.token = self.token
            else:
                self.driver = PetlibroDriver(email=self.email, password=self.password, token=self.token)
            self._persist()
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._poll_loop())
            else:
                try:
                    await self.refresh_feeder()
                    await self._notice("Petlibro connected!")
                except Exception:
                    pass
            return

        if action == "refresh":
            try:
                await self.refresh_feeder()
                await self._notice("Feeder synced")
            except Exception:
                pass
            return

        if action == "feed":
            if self.guest_pin and str(payload.get("pin", "")).strip() != self.guest_pin:
                await self._notice("Invalid or missing household PIN")
                return
            if not self.driver or not self.feeder:
                await self._notice("Petlibro feeder isn't connected yet")
                return
            portions = max(1, min(5, int(payload.get("portions", 1))))
            async with self.bus.lock(self.module_id):
                since = time.monotonic() - self._last_feed
                if not self.feeder.get("online"):
                    await self._notice("Feeder is offline")
                elif since < FEED_COOLDOWN_S:
                    await self._notice("Snack was just dispensed")
                else:
                    self._last_feed = time.monotonic()
                    await self.driver.manual_feed(self.feeder["sn"], portions=portions)
                    self.feeder["today_portions"] = int(self.feeder.get("today_portions", 0)) + portions
                    await self.bus.update(self.module_id, {"feeder": dict(self.feeder)}, origin=client_id)
                    await self._notice(f"Dispensed {portions} snack portion!")
            return

        await super().handle_action(action, payload, client_id)
