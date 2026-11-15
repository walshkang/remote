import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.state_bus import Coalescer


@pytest.mark.asyncio
async def test_coalescer_drops_intermediates():
    sent = []

    async def send(v):
        sent.append(v)

    c = Coalescer(send, interval=0.05)
    for v in range(1, 51):  # simulated slider drag
        c.set(v)
    await asyncio.sleep(0.2)
    await c.aclose()
    assert sent[-1] == 50
    assert len(sent) <= 3


def test_two_clients_sync_and_atomic_deltas(monkeypatch):
    import main

    monkeypatch.setenv("REMOTE_MODULES", "demo")
    main.modules.clear()

    with TestClient(main.app) as client:
        with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
            snap_a, snap_b = a.receive_json(), b.receive_json()
            assert snap_a["type"] == "snapshot" and snap_a["client_id"] != snap_b["client_id"]
            start = snap_a["state"]["demo"]["level"]

            a.send_json({"module": "demo", "action": "delta", "payload": {"delta": 1}})
            b.send_json({"module": "demo", "action": "delta", "payload": {"delta": 1}})

            levels = []
            while len(levels) < 2:
                msg = a.receive_json()
                if msg["type"] == "state" and "level" in msg["patch"]:
                    levels.append(msg["patch"]["level"])
            assert levels == [start + 1, start + 2]  # no lost update


@pytest.mark.asyncio
async def test_state_bus_dispatch_and_macro(monkeypatch):
    import main
    from app.core.state_bus import StateBus
    from app.core.ws_manager import WSManager
    from app.modules.denon.module import Module as DenonModule

    bus = StateBus(WSManager())
    monkeypatch.setenv("DENON_HOST", "")
    denon = DenonModule()
    bus.register(denon.module_id, denon.initial_state())
    bus.register_action_handler(denon.module_id, denon.handle_action)
    await denon.start(bus)

    # Mock main.bus and main.modules cleanly
    monkeypatch.setattr(main, "bus", bus)
    monkeypatch.setattr(main, "modules", {"denon": denon})

    ran = await main.execute_macro("movie_night", "c1")
    assert "denon.power_set" in ran
    assert "denon.set_source" in ran
    assert "denon.volume_set" in ran
    assert bus.get("denon")["power"] == "ON"
    assert bus.get("denon")["source"] == "TV"
    assert bus.get("denon")["volume"] == 52.0

    ran_off = await main.execute_macro("all_off", "c1")
    assert "denon.power_set" in ran_off
    assert bus.get("denon")["power"] == "STANDBY"

    await denon.stop()


def test_pwa_endpoints_and_ws_macro(monkeypatch):
    import main

    monkeypatch.setenv("REMOTE_MODULES", "denon")
    monkeypatch.setenv("DENON_HOST", "")
    main.modules.clear()

    with TestClient(main.app) as client:
        assert client.get("/").status_code == 200
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "modules": ["denon"]}

        manifest = client.get("/manifest.json")
        assert manifest.status_code == 200
        assert manifest.json()["short_name"] == "Remote"

        assert client.get("/sw.js").status_code == 200
        assert client.get("/static/icon.svg").status_code == 200

        with client.websocket_connect("/ws") as ws:
            snap = ws.receive_json()
            assert snap["type"] == "snapshot"
            ws.send_json({"module": "macro", "action": "movie_night"})
            seen_ack = False
            for _ in range(5):
                msg = ws.receive_json()
                if msg.get("type") == "macro_ack":
                    assert msg["scene"] == "movie_night"
                    seen_ack = True
                    break
            assert seen_ack
