"""Philips Hue Bridge driver (CLIP v2 REST + SSE event stream, local LAN)."""
from __future__ import annotations

import asyncio
import colorsys
import json
import logging
from typing import Any, Awaitable, Callable

import httpx

log = logging.getLogger(__name__)


def hs_to_xy(h: float, s: float) -> tuple[float, float]:
    """Hue (0-360) + saturation (0-100) at full value -> CIE xy (Wide RGB D65)."""
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, max(0, min(100, s)) / 100.0, 1.0)

    def gamma(c: float) -> float:
        return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92

    r, g, b = gamma(r), gamma(g), gamma(b)
    X = r * 0.664511 + g * 0.154324 + b * 0.162028
    Y = r * 0.283881 + g * 0.668433 + b * 0.047685
    Z = r * 0.000088 + g * 0.072310 + b * 0.986039
    total = X + Y + Z
    if total == 0:
        return 0.3127, 0.3290
    return round(X / total, 4), round(Y / total, 4)


class HueModel:
    """In-memory model of rooms/zones/lights/scenes. Pure data logic (unit-testable)."""

    def __init__(self) -> None:
        self.lights: dict[str, dict[str, Any]] = {}
        self.groups: dict[str, dict[str, Any]] = {}  # grouped_light id -> {on, brightness}
        self.rooms: list[dict[str, Any]] = []

    def build(self, res: dict[str, list[dict[str, Any]]]) -> None:
        owner_to_light: dict[str, str] = {}
        self.lights = {}
        for l in res.get("light", []):
            self.lights[l["id"]] = self._light_model(l)
            owner_to_light[l.get("owner", {}).get("rid", "")] = l["id"]

        self.groups = {
            g["id"]: {
                "on": g.get("on", {}).get("on", False),
                "brightness": g.get("dimming", {}).get("brightness", 0),
            }
            for g in res.get("grouped_light", [])
        }

        scenes_by_group: dict[str, list[dict[str, str]]] = {}
        for sc in res.get("scene", []):
            gid = sc.get("group", {}).get("rid")
            scenes_by_group.setdefault(gid, []).append({"id": sc["id"], "name": sc["metadata"]["name"]})

        self.rooms = []
        for kind in ("room", "zone"):
            for r in res.get(kind, []):
                light_ids: list[str] = []
                for child in r.get("children", []):
                    if child["rtype"] == "device" and child["rid"] in owner_to_light:
                        light_ids.append(owner_to_light[child["rid"]])
                    elif child["rtype"] == "light" and child["rid"] in self.lights:
                        light_ids.append(child["rid"])
                group_id = next(
                    (s["rid"] for s in r.get("services", []) if s["rtype"] == "grouped_light"), None
                )
                if not light_ids or not group_id:
                    continue
                self.rooms.append({
                    "id": r["id"],
                    "name": r["metadata"]["name"],
                    "kind": kind,
                    "group_id": group_id,
                    "light_ids": light_ids,
                    "scenes": sorted(scenes_by_group.get(r["id"], []), key=lambda s: s["name"]),
                })
        self.rooms.sort(key=lambda r: (r["kind"] != "room", r["name"].lower()))

    @staticmethod
    def _light_model(l: dict[str, Any]) -> dict[str, Any]:
        ct = l.get("color_temperature") or {}
        schema = ct.get("mirek_schema") or {}
        effects = (l.get("effects") or {}).get("status_values") or []
        return {
            "id": l["id"],
            "name": l.get("metadata", {}).get("name", "Light"),
            "on": l.get("on", {}).get("on", False),
            "brightness": l.get("dimming", {}).get("brightness", 100),
            "dimmable": "dimming" in l,
            "xy": (l.get("color") or {}).get("xy"),
            "has_color": "color" in l,
            "has_ct": "color_temperature" in l,
            "mirek": ct.get("mirek"),
            "mirek_min": schema.get("mirek_minimum", 153),
            "mirek_max": schema.get("mirek_maximum", 500),
            "effects": [e for e in effects if e != "no_effect"],
        }

    def apply_event(self, item: dict[str, Any]) -> bool:
        """Apply one SSE update item. Returns True if our model changed."""
        t, rid = item.get("type"), item.get("id")
        if t == "light" and rid in self.lights:
            l = self.lights[rid]
            if "on" in item:
                l["on"] = item["on"]["on"]
            if "dimming" in item:
                l["brightness"] = item["dimming"]["brightness"]
            if "color" in item and "xy" in item["color"]:
                l["xy"] = item["color"]["xy"]
            if "color_temperature" in item and item["color_temperature"].get("mirek") is not None:
                l["mirek"] = item["color_temperature"]["mirek"]
            return True
        if t == "grouped_light" and rid in self.groups:
            g = self.groups[rid]
            if "on" in item:
                g["on"] = item["on"]["on"]
            if "dimming" in item:
                g["brightness"] = item["dimming"]["brightness"]
            return True
        return False

    def snapshot(self) -> dict[str, Any]:
        rooms = []
        for r in self.rooms:
            g = self.groups.get(r["group_id"], {})
            rooms.append({**r, "on": g.get("on", False), "brightness": g.get("brightness", 0)})
        return {"rooms": rooms, "lights": self.lights}


class HueDriver:
    def __init__(
        self,
        host: str,
        app_key: str | None,
        on_change: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self.host = host
        self.app_key = app_key
        self.on_change = on_change
        self.model = HueModel()
        self._client = httpx.AsyncClient(verify=False, timeout=5.0)  # bridge uses a self-signed cert
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def base(self) -> str:
        return f"https://{self.host}"

    def _headers(self) -> dict[str, str]:
        return {"hue-application-key": self.app_key or ""}

    async def pair(self) -> str:
        """Create an app key. Requires the bridge's link button pressed within ~30s."""
        r = await self._client.post(
            f"{self.base}/api", json={"devicetype": "remote#server", "generateclientkey": True}
        )
        data = r.json()[0]
        if "success" in data:
            self.app_key = data["success"]["username"]
            return self.app_key
        raise RuntimeError(data.get("error", {}).get("description", "pairing failed"))

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        await self._client.aclose()

    async def _fetch_all(self) -> dict[str, list[dict[str, Any]]]:
        res: dict[str, list[dict[str, Any]]] = {}
        for rtype in ("light", "grouped_light", "room", "zone", "scene"):
            r = await self._client.get(f"{self.base}/clip/v2/resource/{rtype}", headers=self._headers())
            r.raise_for_status()
            res[rtype] = r.json().get("data", [])
        return res

    async def _publish(self, extra: dict[str, Any] | None = None) -> None:
        await self.on_change({**self.model.snapshot(), **(extra or {})})

    async def _run(self) -> None:
        backoff = 2.0
        while self._running:
            try:
                self.model.build(await self._fetch_all())
                await self._publish({"connected": True, "error": ""})
                backoff = 2.0
                async with self._client.stream(
                    "GET",
                    f"{self.base}/eventstream/clip/v2",
                    headers={**self._headers(), "Accept": "text/event-stream"},
                    timeout=httpx.Timeout(5.0, read=None),
                ) as stream:
                    async for line in stream.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        changed = False
                        for event in json.loads(line[5:]):
                            if event.get("type") == "update":
                                for item in event.get("data", []):
                                    changed |= self.model.apply_event(item)
                        if changed:
                            await self._publish()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("Hue connection error: %s (retry in %.0fs)", e, backoff)
                await self.on_change({"connected": False, "error": str(e)})
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 30.0)

    async def put(self, rtype: str, rid: str, body: dict[str, Any]) -> None:
        r = await self._client.put(
            f"{self.base}/clip/v2/resource/{rtype}/{rid}", headers=self._headers(), json=body
        )
        r.raise_for_status()
