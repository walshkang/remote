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


def test_two_clients_sync_and_atomic_deltas():
    from main import app

    with TestClient(app) as client:
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
