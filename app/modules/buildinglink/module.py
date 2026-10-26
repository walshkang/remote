"""BuildingLink module: open deliveries & front desk package tracking."""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any

from app.core.module_base import RemoteModule
from app.modules.buildinglink.driver import (
    DEFAULT_API_KEY,
    BuildingLinkAuthError,
    BuildingLinkDriver,
    decode_jwt_claims,
    extract_token_input,
)

log = logging.getLogger(__name__)

DATA_FILE = Path(__file__).resolve().parents[3] / "data" / "buildinglink.json"
DEFAULT_POLL_INTERVAL_S = 300  # 5 minutes


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
    module_id = "buildinglink"

    def __init__(self) -> None:
        super().__init__()
        saved = _load_saved()
        self.access_token = (
            os.getenv("BUILDINGLINK_ACCESS_TOKEN", "").strip()
            or saved.get("access_token", "").strip()
        )
        self.refresh_token = (
            os.getenv("BUILDINGLINK_REFRESH_TOKEN", "").strip()
            or saved.get("refresh_token", "").strip()
        )
        self.api_key = (
            os.getenv("BUILDINGLINK_API_KEY", "").strip()
            or saved.get("api_key", "").strip()
            or DEFAULT_API_KEY
        )
        self.poll_interval = int(os.getenv("BUILDINGLINK_POLL_INTERVAL", str(DEFAULT_POLL_INTERVAL_S)))

        claims = {**saved.get("claims", {}), **decode_jwt_claims(self.access_token)}
        self.property_name = str(claims.get("property_name") or saved.get("property_name") or "Northside Piers 2")
        self.unit = str(claims.get("physical_unit_name") or saved.get("unit") or "Unit 6D").replace("  ", " ")
        self.resident = str(claims.get("name") or saved.get("resident") or "")
        self.packages: list[dict[str, Any]] = saved.get("last_packages", [])
        self.last_synced: str = saved.get("last_synced", "")

        self.driver: BuildingLinkDriver | None = None
        self._task: asyncio.Task | None = None

    def initial_state(self) -> dict[str, Any]:
        claims = decode_jwt_claims(self.access_token)
        return {
            "configured": bool(self.access_token),
            "connected": False,
            "property_name": self.property_name,
            "unit": self.unit,
            "resident": self.resident,
            "packages_count": len(self.packages),
            "packages": self.packages,
            "last_synced": self.last_synced,
            "token_expires_at": claims.get("exp"),
            "error": "",
            "notice": "",
        }

    async def start(self, bus) -> None:
        await super().start(bus)
        self.driver = BuildingLinkDriver(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            api_key=self.api_key,
        )
        if self.access_token:
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

    def _persist(self, extra_claims: dict[str, Any] | None = None) -> None:
        claims = {**decode_jwt_claims(self.access_token), **(extra_claims or {})}
        if claims.get("property_name"):
            self.property_name = str(claims["property_name"])
        if claims.get("physical_unit_name"):
            self.unit = str(claims["physical_unit_name"]).replace("  ", " ")
        if claims.get("name"):
            self.resident = str(claims["name"])

        _save_data(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "api_key": self.api_key,
                "property_name": self.property_name,
                "unit": self.unit,
                "resident": self.resident,
                "last_packages": self.packages,
                "last_synced": self.last_synced,
            }
        )

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.refresh_deliveries()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("BuildingLink poll error: %s", e)
            await asyncio.sleep(self.poll_interval)

    async def refresh_deliveries(self) -> list[dict[str, Any]]:
        if not self.driver:
            self.driver = BuildingLinkDriver(
                access_token=self.access_token,
                refresh_token=self.refresh_token,
                api_key=self.api_key,
            )

        try:
            items = await self.driver.fetch_deliveries()
            # Keep tokens synced if driver refreshed them
            self.access_token = self.driver.access_token
            self.refresh_token = self.driver.refresh_token
            self.packages = items
            now_str = datetime.datetime.now().strftime("%-I:%M %p")
            self.last_synced = now_str
            self._persist()

            claims = decode_jwt_claims(self.access_token)
            await self.bus.update(
                self.module_id,
                {
                    "configured": True,
                    "connected": True,
                    "property_name": self.property_name,
                    "unit": self.unit,
                    "resident": self.resident,
                    "packages_count": len(items),
                    "packages": items,
                    "last_synced": now_str,
                    "token_expires_at": claims.get("exp"),
                    "error": "",
                },
            )
            return items
        except BuildingLinkAuthError as e:
            await self.bus.update(
                self.module_id,
                {
                    "connected": False,
                    "error": str(e),
                },
            )
            raise
        except Exception as e:
            await self.bus.update(
                self.module_id,
                {
                    "connected": False,
                    "error": f"Failed to reach BuildingLink: {e}",
                },
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
        if action == "set_token":
            raw = str(payload.get("token", "")).strip()
            if not raw:
                await self._notice("Please paste a valid token or bl.application JSON")
                return

            parsed = extract_token_input(raw)
            self.access_token = parsed["access_token"]
            if parsed.get("refresh_token"):
                self.refresh_token = parsed["refresh_token"]

            if self.driver:
                self.driver.access_token = self.access_token
                if self.refresh_token:
                    self.driver.refresh_token = self.refresh_token

            self._persist(extra_claims=parsed.get("claims"))

            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._poll_loop())
            else:
                try:
                    items = await self.refresh_deliveries()
                    count = len(items)
                    msg = "No packages waiting" if count == 0 else f"{count} package(s) waiting!"
                    await self._notice(f"Connected — {msg}")
                except Exception:
                    pass
            return

        if action == "refresh":
            try:
                items = await self.refresh_deliveries()
                count = len(items)
                msg = "Checked front desk: 0 packages" if count == 0 else f"Found {count} package(s) waiting"
                await self._notice(msg)
            except Exception:
                pass
            return

        await super().handle_action(action, payload, client_id)
