import base64
import json
import time

import httpx
import pytest

from app.core.state_bus import StateBus
from app.core.ws_manager import WSManager
from app.modules.buildinglink.driver import (
    BuildingLinkDriver,
    decode_jwt_claims,
    extract_token_input,
    parse_delivery,
)
from app.modules.buildinglink.module import Module


def _make_fake_jwt(claims: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"{header}.{payload}.fakesig"


def test_decode_and_extract_token():
    exp = int(time.time()) + 900
    jwt_str = _make_fake_jwt(
        {
            "sub": "15581567",
            "name": "Walsh Kang",
            "property_id": "1200",
            "exp": exp,
        }
    )

    claims = decode_jwt_claims(jwt_str)
    assert claims["name"] == "Walsh Kang"
    assert claims["exp"] == exp

    # Extract from bl.application JSON
    bl_app = json.dumps(
        {
            "user": {
                "property_name": "Northside Piers 2",
                "physical_unit_name": "Unit  6D",
            },
            "accessToken": jwt_str,
        }
    )
    parsed = extract_token_input(bl_app)
    assert parsed["access_token"] == jwt_str
    assert parsed["claims"]["property_name"] == "Northside Piers 2"

    # Extract from cURL snippet
    curl_cmd = f"curl 'https://eventlog-us1.buildinglink.com/event-log/resident' -H 'Authorization: Bearer {jwt_str}'"
    assert extract_token_input(curl_cmd)["access_token"] == jwt_str


def test_parse_delivery():
    raw = {
        "eventId": 98765,
        "carrierName": "Amazon",
        "typeDescription": "Medium Box",
        "trackingNumber": "TBA123456789",
        "openComment": "Left at front desk",
        "openDate": "Today 3:15 PM",
        "storageLocation": "Package Room",
    }
    item = parse_delivery(raw)
    assert item["id"] == "98765"
    assert item["carrier"] == "Amazon"
    assert item["tracking"] == "TBA123456789"
    assert item["description"] == "Left at front desk"
    assert item["received_at"] == "Today 3:15 PM"
    assert item["location"] == "Package Room"


@pytest.mark.asyncio
async def test_driver_fetch_and_auto_refresh():
    expired_jwt = _make_fake_jwt({"exp": int(time.time()) - 100})
    fresh_jwt = _make_fake_jwt({"exp": int(time.time()) + 900})

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "connect/token" in str(request.url):
            return httpx.Response(200, json={"access_token": fresh_jwt, "refresh_token": "r2"})
        auth = request.headers.get("Authorization", "")
        if fresh_jwt in auth:
            return httpx.Response(
                200,
                json=[{"id": "1", "carrier": "UPS", "trackingNumber": "1Z999", "openDate": "4:10 PM"}],
            )
        return httpx.Response(401, json={"error": "expired"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        driver = BuildingLinkDriver(
            access_token=expired_jwt,
            refresh_token="r1",
            client=client,
        )
        items = await driver.fetch_deliveries()
        assert len(items) == 1
        assert items[0]["carrier"] == "UPS"
        assert driver.access_token == fresh_jwt
        assert driver.refresh_token == "r2"


@pytest.mark.asyncio
async def test_module_refresh_action(monkeypatch, tmp_path):
    monkeypatch.setattr("app.modules.buildinglink.module.DATA_FILE", tmp_path / "buildinglink.json")
    jwt_str = _make_fake_jwt({"exp": int(time.time()) + 900, "name": "Walsh Kang"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"id": "101", "carrierName": "FedEx", "openComment": "Perishable"},
                {"id": "102", "carrierName": "USPS", "openComment": "Mailbox"},
            ],
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        bus = StateBus(WSManager())
        mod = Module()
        mod.access_token = jwt_str
        mod.driver = BuildingLinkDriver(access_token=jwt_str, client=client)
        bus.register(mod.module_id, mod.initial_state())
        mod.bus = bus

        await mod.handle_action("refresh", {}, "c1")
        state = bus.get(mod.module_id)
        assert state["connected"] is True
        assert state["packages_count"] == 2
        assert state["packages"][0]["carrier"] == "FedEx"
