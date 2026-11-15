import asyncio
import hashlib

import httpx
import pytest

from app.core.state_bus import StateBus
from app.core.ws_manager import WSManager
from app.modules.petlibro.driver import PetlibroDriver, normalize_feeder
from app.modules.petlibro.module import Module


def test_normalize_feeder():
    dev = {"deviceSn": "PL-123", "name": "Granary Dual", "online": True}
    info = {"grainStatus": 1, "powerType": 1, "todayFeedingQuantity": 3}
    snap = normalize_feeder(dev, info)
    assert snap["sn"] == "PL-123"
    assert snap["name"] == "Granary Dual"
    assert snap["online"] is True
    assert snap["food_status"] == "Low"
    assert snap["food_ok"] is False
    assert snap["power_mode"] == "AC Power"
    assert snap["today_portions"] == 3

    empty = normalize_feeder(dev, {"surplusGrain": False})
    assert empty["food_status"] == "Empty"
    assert empty["food_ok"] is False


@pytest.mark.asyncio
async def test_petlibro_driver_login_refresh_and_feed():
    calls = []
    expected_md5 = hashlib.md5(b"secret").hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append((path, request.headers.get("token")))
        if path == "/member/auth/login":
            import json
            body = json.loads(request.content)
            assert body["password"] == expected_md5
            return httpx.Response(200, json={"code": 0, "data": {"token": "fresh-tok"}})
        if path == "/device/device/list":
            if request.headers.get("token") == "expired-tok":
                return httpx.Response(200, json={"code": 1002, "msg": "token expired"})
            return httpx.Response(200, json={"code": 0, "data": [{"deviceSn": "SN1", "name": "Feeder", "online": True}]})
        if path == "/device/device/realInfo":
            return httpx.Response(200, json={"code": 0, "data": {"grainStatus": 0, "powerType": 1, "todayFeedingQuantity": 2}})
        if path == "/device/device/manualFeeding":
            return httpx.Response(200, json={"code": 0, "data": {"ok": True}})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        driver = PetlibroDriver(email="u@example.com", password="secret", token="expired-tok", client=client)
        snap = await driver.fetch_feeder_snapshot()
        assert driver.token == "fresh-tok"
        assert snap["food_status"] == "Full"
        assert snap["today_portions"] == 2

        res = await driver.manual_feed("SN1", portions=1)
        assert res["ok"] is True


@pytest.mark.asyncio
async def test_petlibro_module_cooldown_and_offline(monkeypatch, tmp_path):
    monkeypatch.setattr("app.modules.petlibro.module.DATA_FILE", tmp_path / "petlibro.json")
    feeds = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/device/device/manualFeeding":
            feeds.append(1)
            return httpx.Response(200, json={"code": 0, "data": {"ok": True}})
        return httpx.Response(200, json={"code": 0, "data": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        bus = StateBus(WSManager())
        mod = Module()
        mod.driver = PetlibroDriver(token="tok", client=client)
        mod.feeder = {"sn": "SN1", "name": "Granary", "online": True, "food_status": "Full", "food_ok": True, "today_portions": 1}
        bus.register(mod.module_id, mod.initial_state())
        mod.bus = bus

        # Simultaneous taps must dispense only once due to 60s lock + cooldown
        await asyncio.gather(*(mod.handle_action("feed", {"portions": 1}, f"c{i}") for i in range(3)))
        assert len(feeds) == 1
        assert bus.get(mod.module_id)["feeder"]["today_portions"] == 2

        # Offline guard
        mod._last_feed = 0.0
        mod.feeder["online"] = False
        await mod.handle_action("feed", {"portions": 1}, "c1")
        assert len(feeds) == 1
        assert "offline" in bus.get(mod.module_id)["notice"].lower()
