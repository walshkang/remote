"""Philips Hue module: rooms, individual lights, color, scenes, effects."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from app.core.module_base import RemoteModule
from app.core.state_bus import Coalescer
from app.modules.hue.driver import HueDriver, hs_to_xy

log = logging.getLogger(__name__)

KEY_FILE = Path(__file__).resolve().parents[3] / "data" / "hue.json"  # gitignored


def _load_key() -> str | None:
    if os.getenv("HUE_APP_KEY"):
        return os.environ["HUE_APP_KEY"]
    try:
        return json.loads(KEY_FILE.read_text()).get("app_key")
    except Exception:
        return None


def _save_key(key: str) -> None:
    KEY_FILE.parent.mkdir(exist_ok=True)
    KEY_FILE.write_text(json.dumps({"app_key": key}))
    KEY_FILE.chmod(0o600)


class Module(RemoteModule):
    module_id = "hue"

    def __init__(self) -> None:
        super().__init__()
        self.host = os.getenv("HUE_HOST", "192.168.1.154").strip()
        self.driver: HueDriver | None = None
        self._coalescers: dict[str, Coalescer] = {}

    def initial_state(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "paired": bool(_load_key()),
            "connected": False,
            "error": "",
            "rooms": [],
            "lights": {},
        }

    async def start(self, bus) -> None:
        await super().start(bus)
        if _load_key():
            await self._start_driver()

    async def _start_driver(self) -> None:
        self.driver = HueDriver(self.host, _load_key(), self._on_change)
        await self.driver.start()

    async def stop(self) -> None:
        for c in self._coalescers.values():
            await c.aclose()
        if self.driver:
            await self.driver.stop()

    async def _on_change(self, patch: dict[str, Any]) -> None:
        await self.bus.update(self.module_id, patch)

    def _coalesce(self, key: str, interval: float, send, value: Any) -> None:
        """Latest-value-wins per key (hue rooms tolerate ~1-2/s, single lights ~10/s)."""
        if key not in self._coalescers:
            self._coalescers[key] = Coalescer(send, interval)
        self._coalescers[key].set(value)

    async def _optimistic(self, client_id: str) -> None:
        await self.bus.update(self.module_id, self.driver.model.snapshot(), origin=client_id)

    async def handle_action(self, action: str, payload: dict[str, Any], client_id: str) -> None:
        if action == "pair":
            await self._pair()
            return
        d = self.driver
        if d is None:
            raise RuntimeError("Hue bridge not paired")
        m = d.model

        if action == "room_toggle":
            room = next(r for r in m.rooms if r["id"] == payload["room"])
            on = bool(payload["on"])
            m.groups[room["group_id"]]["on"] = on
            await self._optimistic(client_id)
            await d.put("grouped_light", room["group_id"], {"on": {"on": on}})

        elif action == "room_brightness":
            room = next(r for r in m.rooms if r["id"] == payload["room"])
            b = max(1.0, min(100.0, float(payload["value"])))
            g = m.groups[room["group_id"]]
            g["brightness"], g["on"] = b, True
            await self._optimistic(client_id)
            gid = room["group_id"]

            async def send(v, gid=gid):
                await d.put(
                    "grouped_light",
                    gid,
                    {"on": {"on": True}, "dimming": {"brightness": v}, "dynamics": {"duration": 150}},
                )

            self._coalesce(f"g:{gid}", 0.15, send, b)

        elif action == "room_color":
            room = next(r for r in m.rooms if r["id"] == payload["room"])
            xy = hs_to_xy(float(payload["h"]), float(payload["s"]))
            for lid in room["light_ids"]:
                if m.lights[lid]["has_color"]:
                    m.lights[lid]["xy"], m.lights[lid]["on"] = list(xy), True
                    await self._send_light_color(lid, xy)
            await self._optimistic(client_id)

        elif action == "room_temp":
            room = next(r for r in m.rooms if r["id"] == payload["room"])
            mirek_req = int(payload["mirek"])
            for lid in room["light_ids"]:
                light = m.lights[lid]
                if light["has_ct"]:
                    mirek = int(max(light["mirek_min"], min(light["mirek_max"], mirek_req)))
                    light["mirek"], light["xy"], light["on"] = mirek, None, True

                    async def send_ct(v, lid=lid):
                        await d.put("light", lid, {"on": {"on": True}, "color_temperature": {"mirek": v}})

                    self._coalesce(f"t:{lid}", 0.15, send_ct, mirek)
            await self._optimistic(client_id)

        elif action == "scene_recall":
            await d.put("scene", payload["scene"], {"recall": {"action": "active"}})

        elif action == "light_toggle":
            lid, on = payload["light"], bool(payload["on"])
            m.lights[lid]["on"] = on
            await self._optimistic(client_id)
            await d.put("light", lid, {"on": {"on": on}})

        elif action == "light_brightness":
            lid = payload["light"]
            b = max(1.0, min(100.0, float(payload["value"])))
            m.lights[lid]["brightness"], m.lights[lid]["on"] = b, True
            await self._optimistic(client_id)

            async def send(v, lid=lid):
                await d.put(
                    "light",
                    lid,
                    {"on": {"on": True}, "dimming": {"brightness": v}, "dynamics": {"duration": 150}},
                )

            self._coalesce(f"l:{lid}", 0.1, send, b)

        elif action == "light_color":
            lid = payload["light"]
            xy = hs_to_xy(float(payload["h"]), float(payload["s"]))
            m.lights[lid]["xy"], m.lights[lid]["on"] = list(xy), True
            await self._optimistic(client_id)
            await self._send_light_color(lid, xy)

        elif action == "light_temp":
            lid = payload["light"]
            light = m.lights[lid]
            mirek = int(max(light["mirek_min"], min(light["mirek_max"], int(payload["mirek"]))))
            light["mirek"], light["xy"], light["on"] = mirek, None, True
            await self._optimistic(client_id)

            async def send(v, lid=lid):
                await d.put("light", lid, {"on": {"on": True}, "color_temperature": {"mirek": v}})

            self._coalesce(f"t:{lid}", 0.1, send, mirek)

        elif action == "light_effect":
            lid, effect = payload["light"], str(payload["effect"])
            await d.put("light", lid, {"effects": {"effect": effect}})

        else:
            await super().handle_action(action, payload, client_id)

    async def _send_light_color(self, lid: str, xy: tuple[float, float]) -> None:
        async def send(v, lid=lid):
            await self.driver.put(
                "light", lid, {"on": {"on": True}, "color": {"xy": {"x": v[0], "y": v[1]}}}
            )

        self._coalesce(f"c:{lid}", 0.1, send, xy)

    async def _pair(self) -> None:
        """Called after the user presses the bridge's link button."""
        tmp = HueDriver(self.host, None, self._on_change)
        try:
            key = await tmp.pair()
        except Exception as e:
            await self.bus.update(self.module_id, {"error": f"Press the bridge button, then retry ({e})"})
            return
        finally:
            await tmp._client.aclose()
        _save_key(key)
        await self.bus.update(self.module_id, {"paired": True, "error": ""})
        if self.driver:
            await self.driver.stop()
        await self._start_driver()
