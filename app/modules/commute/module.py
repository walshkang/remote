"""Going Out & Commute module: Bedford Av L train, NYC Ferry, Citi Bike, and weather."""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import Any

from app.core.module_base import RemoteModule
from app.modules.commute.driver import (
    DEFAULT_CITIBIKE_STATIONS,
    DEFAULT_LAT,
    DEFAULT_LON,
    DEFAULT_WALK_MINUTES,
    NY_TZ,
    CommuteDriver,
)

log = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_S = 60


class Module(RemoteModule):
    module_id = "commute"

    def __init__(self) -> None:
        super().__init__()
        self.lat = float(os.getenv("WEATHER_LAT", str(DEFAULT_LAT)))
        self.lon = float(os.getenv("WEATHER_LON", str(DEFAULT_LON)))
        self.walk_minutes = int(os.getenv("SUBWAY_WALK_MINUTES", str(DEFAULT_WALK_MINUTES)))
        self.poll_interval = int(os.getenv("COMMUTE_POLL_INTERVAL", str(DEFAULT_POLL_INTERVAL_S)))

        raw_stations = os.getenv("CITIBIKE_STATIONS", "").strip()
        stations = [s.strip() for s in raw_stations.split(",") if s.strip()] if raw_stations else DEFAULT_CITIBIKE_STATIONS
        self.stations = stations

        self.driver: CommuteDriver | None = None
        self._task: asyncio.Task | None = None

    def initial_state(self) -> dict[str, Any]:
        return {
            "connected": False,
            "neighborhood": "North Williamsburg",
            "weather": None,
            "subway": None,
            "ferry": None,
            "citibike": None,
            "last_updated": "",
            "errors": {},
        }

    async def start(self, bus) -> None:
        await super().start(bus)
        self.driver = CommuteDriver(
            lat=self.lat,
            lon=self.lon,
            walk_minutes=self.walk_minutes,
            citibike_stations=self.stations,
        )
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

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.refresh_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("Commute poll error: %s", e)
            await asyncio.sleep(self.poll_interval)

    async def refresh_all(self) -> dict[str, Any]:
        if not self.driver:
            self.driver = CommuteDriver(
                lat=self.lat,
                lon=self.lon,
                walk_minutes=self.walk_minutes,
                citibike_stations=self.stations,
            )

        results = await asyncio.gather(
            self.driver.fetch_weather(),
            self.driver.fetch_mta_l_train(),
            self.driver.fetch_nyc_ferry(),
            self.driver.fetch_citibike(),
            return_exceptions=True,
        )
        names = ("weather", "subway", "ferry", "citibike")
        cur = self.bus.get(self.module_id) if self.bus else {}
        patch: dict[str, Any] = {}
        errors: dict[str, str] = {}

        for key, res in zip(names, results):
            if isinstance(res, Exception):
                log.debug("Commute sub-fetch %s failed: %s", key, res)
                errors[key] = str(res)
                if cur.get(key) is not None:
                    patch[key] = cur[key]
            else:
                patch[key] = res

        ok_count = sum(1 for r in results if not isinstance(r, Exception))
        patch["connected"] = ok_count > 0
        patch["errors"] = errors
        patch["last_updated"] = datetime.datetime.now(NY_TZ).strftime("%-I:%M %p")

        if self.bus:
            await self.bus.update(self.module_id, patch)
        return patch

    async def handle_action(self, action: str, payload: dict[str, Any], client_id: str) -> None:
        if action == "refresh":
            await self.refresh_all()
            return
        await super().handle_action(action, payload, client_id)
