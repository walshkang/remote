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
        try:
            await m.start(bus)
        except Exception:
            log.exception("module %s failed to start", m.module_id)
    log.info("modules loaded: %s", list(modules))
    yield
    for m in modules.values():
        await m.stop()


app = FastAPI(title="Remote", lifespan=lifespan)


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    client_id = uuid.uuid4().hex[:8]
    await ws_manager.connect(client_id, ws)
    await ws_manager.send(client_id, {**bus.snapshot(), "client_id": client_id})
    try:
        while True:
            msg = await ws.receive_json()
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
