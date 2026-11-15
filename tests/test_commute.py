import io
import time
import zipfile

import httpx
import pytest

from app.core.state_bus import StateBus
from app.core.ws_manager import WSManager
from app.modules.commute.driver import CommuteDriver, parse_gtfs_rt
from app.modules.commute.module import Module


def _encode_varint(n: int) -> bytes:
    if n < 0:
        n += 1 << 64
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _field_varint(num: int, val: int) -> bytes:
    return _encode_varint((num << 3) | 0) + _encode_varint(val)


def _field_bytes(num: int, data: bytes) -> bytes:
    return _encode_varint((num << 3) | 2) + _encode_varint(len(data)) + data


def _build_sample_gtfs_rt(now: int) -> bytes:
    # TripUpdate for L train stopping at L08N in 6 min and L08S in 2 min
    td = _field_bytes(1, b"trip-1") + _field_bytes(5, b"L")
    ev_n = _field_varint(2, now + 360)
    stu_n = _field_bytes(2, ev_n) + _field_bytes(4, b"L08N")
    ev_s = _field_varint(2, now + 120)
    stu_s = _field_bytes(3, ev_s) + _field_bytes(4, b"L08S")
    tu = _field_bytes(1, td) + _field_bytes(2, stu_n) + _field_bytes(2, stu_s)
    ent1 = _field_bytes(1, b"e1") + _field_bytes(3, tu)

    # Active Alert for route L
    tr = _field_varint(1, now - 60) + _field_varint(2, now + 600)
    inf = _field_bytes(2, b"L")
    trans = _field_bytes(1, b"L trains running with delays")
    hdr = _field_bytes(1, trans)
    alert = _field_bytes(1, tr) + _field_bytes(5, inf) + _field_bytes(10, hdr)
    ent2 = _field_bytes(1, b"e2") + _field_bytes(5, alert)

    return _field_bytes(2, ent1) + _field_bytes(2, ent2)


def _build_ferry_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "calendar.txt",
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "ALL,1,1,1,1,1,1,1,20200101,20301231\n",
        )
        z.writestr("calendar_dates.txt", "service_id,date,exception_type\n")
        z.writestr(
            "trips.txt",
            "route_id,service_id,trip_id,trip_headsign,direction_id\n"
            "ER,ALL,t1,Wall St./Pier 11,0\n"
            "ER,ALL,t2,East 34th Street,1\n",
        )
        z.writestr(
            "stop_times.txt",
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "t1,13:15:00,13:15:00,19,4\n"
            "t2,13:25:00,13:25:00,19,4\n",
        )
    return buf.getvalue()


def test_parse_gtfs_rt():
    now = 1_794_765_000
    raw = _build_sample_gtfs_rt(now)
    parsed = parse_gtfs_rt(raw, stop_ids={"L08N", "L08S"}, route_filter="L", now=now)

    assert len(parsed["arrivals"]["L08N"]) == 1
    assert parsed["arrivals"]["L08N"][0]["minutes"] == 6
    assert len(parsed["arrivals"]["L08S"]) == 1
    assert parsed["arrivals"]["L08S"][0]["minutes"] == 2
    assert parsed["alerts"] == ["L trains running with delays"]


@pytest.mark.asyncio
async def test_commute_driver_fetches():
    now = 1_794_765_000
    gtfs_rt = _build_sample_gtfs_rt(now)
    ferry_zip = _build_ferry_zip()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gtfs-l" in url or "subway-alerts" in url:
            return httpx.Response(200, content=gtfs_rt)
        if "gtfs.aspx" in url:
            return httpx.Response(200, content=ferry_zip)
        if "gtfsrealtime.aspx" in url:
            return httpx.Response(200, content=b"")
        if "station_information" in url:
            return httpx.Response(
                200,
                json={"data": {"stations": [{"station_id": "s1", "name": "N 5 St & Wythe Ave"}]}},
            )
        if "station_status" in url:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "stations": [
                            {
                                "station_id": "s1",
                                "num_bikes_available": 10,
                                "num_ebikes_available": 4,
                                "num_docks_available": 12,
                                "is_renting": 1,
                                "is_returning": 1,
                            }
                        ]
                    }
                },
            )
        if "open-meteo" in url:
            return httpx.Response(
                200,
                json={
                    "current": {
                        "time": "2026-11-15T13:00",
                        "temperature_2m": 52.3,
                        "apparent_temperature": 48.0,
                        "weather_code": 1,
                        "precipitation": 0.0,
                        "wind_speed_10m": 8.2,
                    },
                    "hourly": {
                        "time": ["2026-11-15T13:00", "2026-11-15T14:00", "2026-11-15T15:00"],
                        "precipitation_probability": [0, 70, 20],
                    },
                    "daily": {"sunset": ["2026-11-15T16:37"]},
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        driver = CommuteDriver(walk_minutes=4, citibike_stations=["s1"], client=client)

        subway = await driver.fetch_mta_l_train(now=now)
        assert subway["manhattan"] == [{"minutes": 6, "reachable": True}]
        assert subway["brooklyn"] == [{"minutes": 2, "reachable": False}]
        assert subway["alerts"] == ["L trains running with delays"]

        cb = await driver.fetch_citibike()
        assert cb["stations"][0]["ebikes"] == 4
        assert cb["stations"][0]["classic"] == 6
        assert cb["stations"][0]["docks"] == 12

        weather = await driver.fetch_weather()
        assert weather["temp_f"] == 52
        assert "Rain likely in ~1h (70%)" in weather["headline"]
        assert weather["sunset"] == "4:37 PM"

        # Test ferry around 13:00 Eastern (1794765600 is 2026-11-15 13:00 EST)
        import datetime
        from zoneinfo import ZoneInfo

        noon_ts = datetime.datetime(2026, 11, 15, 13, 0, tzinfo=ZoneInfo("America/New_York")).timestamp()
        ferry = await driver.fetch_nyc_ferry(now=noon_ts)
        assert ferry["southbound"][0]["minutes"] == 15
        assert ferry["northbound"][0]["minutes"] == 25


@pytest.mark.asyncio
async def test_commute_module_refresh(monkeypatch):
    now = int(time.time())
    gtfs_rt = _build_sample_gtfs_rt(now)
    ferry_zip = _build_ferry_zip()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gtfs-l" in url or "subway-alerts" in url:
            return httpx.Response(200, content=gtfs_rt)
        if "gtfs.aspx" in url:
            return httpx.Response(200, content=ferry_zip)
        if "gtfsrealtime.aspx" in url:
            return httpx.Response(200, content=b"")
        if "station_information" in url:
            return httpx.Response(200, json={"data": {"stations": []}})
        if "station_status" in url:
            return httpx.Response(200, json={"data": {"stations": []}})
        if "open-meteo" in url:
            return httpx.Response(
                200,
                json={
                    "current": {"time": "2026-11-15T13:00", "temperature_2m": 60, "apparent_temperature": 60, "weather_code": 0, "wind_speed_10m": 5},
                    "hourly": {"time": [], "precipitation_probability": []},
                    "daily": {"sunset": []},
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        bus = StateBus(WSManager())
        mod = Module()
        mod.driver = CommuteDriver(client=client)
        bus.register(mod.module_id, mod.initial_state())
        mod.bus = bus

        await mod.handle_action("refresh", {}, "c1")
        state = bus.get(mod.module_id)
        assert state["connected"] is True
        assert state["weather"]["temp_f"] == 60
        assert state["subway"]["station"] == "Bedford Av"
