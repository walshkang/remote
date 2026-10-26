"""Litter-Robot 4 module (Whisker cloud via pylitterbot, websocket push + poll fallback)."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from app.core.module_base import RemoteModule

log = logging.getLogger(__name__)

CLEAN_COOLDOWN_S = 60  # server-side guard against double taps / retries
POLL_INTERVAL_S = 60  # safety net if the websocket silently drops


def robot_snapshot(robot: Any) -> dict[str, Any]:
    """Plain-dict view of a LitterRobot4 (kept separate so it's unit-testable)."""
    status = robot.status
    return {
        "name": robot.name,
        "online": bool(robot.is_online),
        "power_on": bool(robot.is_on),
        "status": status.name,
        "status_text": status.text or status.name.title(),
        "cycling": status.name in ("CLEAN_CYCLE", "EMPTY_CYCLE"),
        "cat_detected": status.name in ("CAT_DETECTED", "CAT_SENSOR_TIMING", "CAT_SENSOR_INTERRUPTED"),
        "drawer_full": bool(robot.is_waste_drawer_full),
        "waste_level": round(float(robot.waste_drawer_level), 1),
        "litter_level": round(float(robot.litter_level), 1),
        "pet_weight": round(float(robot.pet_weight), 1),
        "night_light": bool(robot.night_light_mode_enabled),
        "panel_lock": bool(robot.panel_lock_enabled),
        "wait_minutes": int(robot.clean_cycle_wait_time_minutes),
    }


class Module(RemoteModule):
    module_id = "litter_robot"

    def __init__(self) -> None:
        super().__init__()
        self.email = os.getenv("LITTER_ROBOT_EMAIL", "").strip()
        self.password = os.getenv("LITTER_ROBOT_PASSWORD", "")
        self.account = None
        self.robot = None
        self._task: asyncio.Task | None = None
        self._last_clean = 0.0
        self._loop: asyncio.AbstractEventLoop | None = None

    def initial_state(self) -> dict[str, Any]:
        return {
            "configured": bool(self.email and self.password),
            "connected": False,
            "error": "",
            "notice": "",
            "robot": None,
        }

    async def start(self, bus) -> None:
        await super().start(bus)
        self._loop = asyncio.get_running_loop()
        if self.email and self.password:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self.robot:
            try:
                await self.robot.unsubscribe()
            except Exception:
                pass
        if self.account:
            try:
                await self.account.disconnect()
            except Exception:
                pass

    async def _publish(self) -> None:
        await self.bus.update(
            self.module_id, {"connected": True, "error": "", "robot": robot_snapshot(self.robot)}
        )

    def _on_robot_update(self) -> None:
        # pylitterbot invokes listeners synchronously from its own callbacks.
        if self._loop and self.robot:
            self._loop.call_soon_threadsafe(lambda: asyncio.create_task(self._publish()))

    async def _run(self) -> None:
        from pylitterbot import Account
        from pylitterbot.event import EVENT_UPDATE
        from pylitterbot.robot.litterrobot4 import LitterRobot4

        backoff = 5.0
        while True:
            try:
                self.account = Account()
                await self.account.connect(
                    username=self.email,
                    password=self.password,
                    load_robots=True,
                    subscribe_for_updates=True,
                    robot_types=[LitterRobot4],
                )
                robots = [r for r in self.account.robots if isinstance(r, LitterRobot4)]
                if not robots:
                    raise RuntimeError("No Litter-Robot 4 found on this Whisker account")
                self.robot = robots[0]
                self.robot.on(EVENT_UPDATE, self._on_robot_update)
                await self._publish()
                backoff = 5.0
                while True:  # poll fallback; websocket pushes arrive via _on_robot_update
                    await asyncio.sleep(POLL_INTERVAL_S)
                    await self.robot.refresh()
                    await self._publish()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("Litter-Robot error: %s (retry in %.0fs)", e, backoff)
                await self.bus.update(self.module_id, {"connected": False, "error": str(e)})
                try:
                    if self.account:
                        await self.account.disconnect()
                except Exception:
                    pass
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300.0)

    async def _notice(self, text: str) -> None:
        """Show a transient message on every connected screen, auto-cleared after 6s."""
        await self.bus.update(self.module_id, {"notice": text})

        async def clear() -> None:
            await asyncio.sleep(6)
            if self.bus.get(self.module_id).get("notice") == text:
                await self.bus.update(self.module_id, {"notice": ""})

        asyncio.create_task(clear())

    async def handle_action(self, action: str, payload: dict[str, Any], client_id: str) -> None:
        if self.robot is None:
            await self._notice("Litter-Robot isn't connected yet")
            return

        if action == "clean":
            async with self.bus.lock(self.module_id):  # serialize simultaneous taps
                snap = robot_snapshot(self.robot)
                since = time.monotonic() - self._last_clean
                if snap["cat_detected"]:
                    await self._notice("A cat is in the box - not starting a cycle")
                elif snap["cycling"] or since < CLEAN_COOLDOWN_S:
                    await self._notice("A clean cycle was just started")
                elif not snap["online"] or not snap["power_on"]:
                    await self._notice("Litter-Robot is offline or powered off")
                else:
                    self._last_clean = time.monotonic()
                    ok = await self.robot.start_cleaning()
                    await self._notice("Clean cycle started" if ok else "Robot rejected the command")

        elif action == "night_light":
            await self.robot.set_night_light(bool(payload["on"]))
            await self.robot.refresh()
            await self._publish()

        elif action == "panel_lock":
            await self.robot.set_panel_lockout(bool(payload["on"]))
            await self.robot.refresh()
            await self._publish()

        else:
            await super().handle_action(action, payload, client_id)
