"""Remote: modular LAN remote. Run: uv run uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1"""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()  # read .env (gitignored) before modules are loaded

from app.core.registry import load_modules
from app.core.state_bus import StateBus
from app.core.ws_manager import WSManager

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("remote")

STATIC = Path(__file__).parent / "static"

ws_manager = WSManager()
bus = StateBus(ws_manager)
modules = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    for m in load_modules():
        modules[m.module_id] = m
        bus.register(m.module_id, m.initial_state())
        bus.register_action_handler(m.module_id, m.handle_action)
        try:
            await m.start(bus)
        except Exception:
            log.exception("module %s failed to start", m.module_id)
    log.info("modules loaded: %s", list(modules))
    yield
    for m in modules.values():
        await m.stop()


async def execute_macro(scene: str, client_id: str) -> list[str]:
    """Run a 1-tap cross-device scene across loaded modules."""
    ran: list[str] = []

    async def safe_dispatch(mod_id: str, action: str, payload: dict | None = None) -> None:
        try:
            if await bus.dispatch(mod_id, action, payload or {}, client_id=client_id):
                ran.append(f"{mod_id}.{action}")
        except Exception as exc:
            log.debug("macro %s skipped %s.%s: %s", scene, mod_id, action, exc)

    hue_rooms = (bus.get("hue").get("rooms", []) if "hue" in modules else [])
    hue_paired = bool(bus.get("hue").get("paired")) if "hue" in modules else False

    if scene == "movie_night":
        await safe_dispatch("denon", "power_set", {"power": "ON"})
        await safe_dispatch("denon", "set_source", {"source": "TV"})
        await safe_dispatch("denon", "volume_set", {"value": 52.0})
        if hue_paired:
            for room in hue_rooms:
                rid = room["id"]
                await safe_dispatch("hue", "room_toggle", {"room": rid, "on": True})
                await safe_dispatch("hue", "room_brightness", {"room": rid, "value": 20})
                await safe_dispatch("hue", "room_temp", {"room": rid, "mirek": 454})

    elif scene == "relax":
        if hue_paired:
            for room in hue_rooms:
                rid = room["id"]
                await safe_dispatch("hue", "room_toggle", {"room": rid, "on": True})
                await safe_dispatch("hue", "room_brightness", {"room": rid, "value": 65})
                await safe_dispatch("hue", "room_temp", {"room": rid, "mirek": 370})

    elif scene == "goodnight":
        if hue_paired:
            for room in hue_rooms:
                await safe_dispatch("hue", "room_toggle", {"room": room["id"], "on": False})
        await safe_dispatch("denon", "power_set", {"power": "STANDBY"})
        if "litter_robot" in modules and bus.get("litter_robot").get("robot"):
            await safe_dispatch("litter_robot", "night_light", {"on": True})

    elif scene == "all_off":
        if hue_paired:
            for room in hue_rooms:
                await safe_dispatch("hue", "room_toggle", {"room": room["id"], "on": False})
        await safe_dispatch("denon", "power_set", {"power": "STANDBY"})

    else:
        raise ValueError(f"unknown macro scene {scene!r}")

    return ran


app = FastAPI(title="Remote", lifespan=lifespan)


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/manifest.json")
async def manifest():
    return FileResponse(STATIC / "manifest.json", media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript")


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "modules": list(modules.keys())}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    client_id = uuid.uuid4().hex[:8]
    await ws_manager.connect(client_id, ws)
    await ws_manager.send(client_id, {**bus.snapshot(), "client_id": client_id})
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("module") == "macro":
                try:
                    ran = await execute_macro(msg["action"], client_id)
                    await ws_manager.send(
                        client_id,
                        {"type": "macro_ack", "scene": msg["action"], "applied": ran},
                    )
                except Exception as e:
                    await ws_manager.send(client_id, {"type": "error", "module": "macro", "error": str(e)})
                continue
            module = modules.get(msg.get("module"))
            if module is None:
                await ws_manager.send(client_id, {"type": "error", "error": "unknown module"})
                continue
            try:
                await module.handle_action(msg["action"], msg.get("payload", {}), client_id)
            except Exception as e:
                log.exception("action failed")
                await ws_manager.send(client_id, {"type": "error", "module": module.module_id, "error": str(e)})
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(client_id)


app.mount("/static", StaticFiles(directory=STATIC), name="static")
