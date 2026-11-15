"""Async driver for North Williamsburg commute & weather feeds:
- MTA L Train (Bedford Av L08N/L08S) + Subway Alerts (pure-Python GTFS-RT)
- NYC Ferry (North Williamsburg Stop 19, GTFS static + GTFS-RT)
- Citi Bike GBFS 2.3 (North Williamsburg stations)
- Open-Meteo hyperlocal weather
"""
from __future__ import annotations

import csv
import datetime
import io
import logging
import time
import zipfile
from typing import Any, Iterator
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")

MTA_L_FEED_URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l"
MTA_ALERTS_URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts"
CITIBIKE_INFO_URL = "https://gbfs.lyft.com/gbfs/2.3/bkn/en/station_information.json"
CITIBIKE_STATUS_URL = "https://gbfs.lyft.com/gbfs/2.3/bkn/en/station_status.json"
FERRY_GTFS_URL = "https://nycferry.connexionz.net/rtt/public/utility/gtfs.aspx"
FERRY_RT_URL = "https://nycferry.connexionz.net/rtt/public/utility/gtfsrealtime.aspx/tripupdate"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

DEFAULT_LAT = 40.7181
DEFAULT_LON = -73.9571
DEFAULT_WALK_MINUTES = 4
DEFAULT_FERRY_STOP_ID = "19"

DEFAULT_CITIBIKE_STATIONS = [
    "1786697003367719132",                  # N 5 St & Wythe Ave
    "66dcac42-0aca-11e7-82f6-3863bb44ef7c", # Kent Ave & N 7 St
    "66dd039b-0aca-11e7-82f6-3863bb44ef7c", # N 6 St & Bedford Ave
    "2263853517922976822",                  # Berry St & N 4 St
]

WMO_CODES: dict[int, tuple[str, str]] = {
    0: ("Clear", "☀️"),
    1: ("Mostly Clear", "🌤️"),
    2: ("Partly Cloudy", "⛅"),
    3: ("Cloudy", "☁️"),
    45: ("Fog", "🌫️"),
    48: ("Fog", "🌫️"),
    51: ("Light Drizzle", "🌦️"),
    53: ("Drizzle", "🌦️"),
    55: ("Heavy Drizzle", "🌧️"),
    56: ("Freezing Drizzle", "🌨️"),
    57: ("Freezing Drizzle", "🌨️"),
    61: ("Light Rain", "🌧️"),
    63: ("Rain", "🌧️"),
    65: ("Heavy Rain", "🌧️"),
    66: ("Freezing Rain", "🌨️"),
    67: ("Freezing Rain", "🌨️"),
    71: ("Light Snow", "🌨️"),
    73: ("Snow", "🌨️"),
    75: ("Heavy Snow", "❄️"),
    77: ("Snow Grains", "❄️"),
    80: ("Rain Showers", "🌦️"),
    81: ("Showers", "🌧️"),
    82: ("Heavy Showers", "⛈️"),
    85: ("Snow Showers", "🌨️"),
    86: ("Heavy Snow", "❄️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm", "⛈️"),
    99: ("Severe Storm", "⛈️"),
}


# ---------------------------------------------------------------------------
# Pure-Python Protobuf / GTFS-Realtime Wire Decoder
# ---------------------------------------------------------------------------

def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    res, shift = 0, 0
    n = len(buf)
    while pos < n:
        b = buf[pos]
        pos += 1
        res |= (b & 0x7F) << shift
        if not (b & 0x80):
            return res, pos
        shift += 7
    raise ValueError("Truncated varint in protobuf payload")


def _signed_varint(val: int) -> int:
    if val >= (1 << 63):
        return val - (1 << 64)
    return val


def _iter_fields(buf: bytes) -> Iterator[tuple[int, int, Any]]:
    pos, n = 0, len(buf)
    while pos < n:
        tag, pos = _read_varint(buf, pos)
        field_num, wire_type = tag >> 3, tag & 0x7
        if wire_type == 0:
            val, pos = _read_varint(buf, pos)
        elif wire_type == 1:
            if pos + 8 > n:
                break
            val = buf[pos : pos + 8]
            pos += 8
        elif wire_type == 2:
            length, pos = _read_varint(buf, pos)
            if pos + length > n:
                break
            val = buf[pos : pos + length]
            pos += length
        elif wire_type == 5:
            if pos + 4 > n:
                break
            val = buf[pos : pos + 4]
            pos += 4
        else:
            break
        yield field_num, wire_type, val


def _parse_stop_time_event(buf: bytes) -> tuple[int | None, int | None]:
    """Decode StopTimeEvent -> (delay_s, unix_timestamp)."""
    delay: int | None = None
    ts: int | None = None
    for f, w, v in _iter_fields(buf):
        if f == 1 and w == 0:
            delay = _signed_varint(v)
        elif f == 2 and w == 0:
            ts = _signed_varint(v)
    return delay, ts


def _parse_translated_string(buf: bytes) -> str:
    """Decode TranslatedString -> first non-empty Translation.text."""
    for f, w, v in _iter_fields(buf):
        if f == 1 and w == 2:
            for tf, tw, tv in _iter_fields(v):
                if tf == 1 and tw == 2:
                    text = tv.decode("utf-8", "ignore").strip()
                    if text:
                        return text
    return ""


def parse_gtfs_rt(
    raw: bytes,
    stop_ids: set[str] | None = None,
    route_filter: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Decode a GTFS-RT FeedMessage into stop arrivals, trip updates, and alerts."""
    now_ts = time.time() if now is None else now
    arrivals: dict[str, list[dict[str, Any]]] = {sid: [] for sid in (stop_ids or set())}
    trip_updates: dict[str, dict[str, dict[str, Any]]] = {}
    alerts: list[str] = []
    seen_alerts: set[str] = set()

    for fnum, wtype, entity in _iter_fields(raw):
        if fnum != 2 or wtype != 2:
            continue
        for ef, ew, eval_ in _iter_fields(entity):
            if ef == 3 and ew == 2:  # TripUpdate
                trip_id = ""
                route_id = ""
                stu_list: list[tuple[str, int | None, int | None]] = []
                for tf, tw, tval in _iter_fields(eval_):
                    if tf == 1 and tw == 2:  # TripDescriptor
                        for df, dw, dval in _iter_fields(tval):
                            if df == 1 and dw == 2:
                                trip_id = dval.decode("utf-8", "ignore")
                            elif df == 5 and dw == 2:
                                route_id = dval.decode("utf-8", "ignore")
                    elif tf == 2 and tw == 2:  # StopTimeUpdate
                        sid = ""
                        arr_delay, arr_ts = None, None
                        dep_delay, dep_ts = None, None
                        for sf, sw, sval in _iter_fields(tval):
                            if sf == 2 and sw == 2:
                                arr_delay, arr_ts = _parse_stop_time_event(sval)
                            elif sf == 3 and sw == 2:
                                dep_delay, dep_ts = _parse_stop_time_event(sval)
                            elif sf == 4 and sw == 2:
                                sid = sval.decode("utf-8", "ignore")
                        ts = arr_ts if arr_ts is not None else dep_ts
                        delay = arr_delay if arr_delay is not None else dep_delay
                        if sid:
                            stu_list.append((sid, ts, delay))

                if route_filter and route_id and route_id != route_filter:
                    continue

                for sid, ts, delay in stu_list:
                    if trip_id:
                        trip_updates.setdefault(trip_id, {})[sid] = {"time": ts, "delay": delay}
                    if (stop_ids is None or sid in stop_ids) and ts is not None and ts >= now_ts - 15:
                        mins = max(0, round((ts - now_ts) / 60.0))
                        arrivals.setdefault(sid, []).append(
                            {
                                "time": ts,
                                "minutes": mins,
                                "trip_id": trip_id,
                                "route_id": route_id,
                                "delay": delay or 0,
                            }
                        )

            elif ef == 5 and ew == 2:  # Alert
                routes: set[str] = set()
                stops: set[str] = set()
                periods: list[tuple[int, int]] = []
                header = ""
                for af, aw, aval in _iter_fields(eval_):
                    if af == 1 and aw == 2:
                        start, end = 0, 10**12
                        for pf, pw, pval in _iter_fields(aval):
                            if pf == 1 and pw == 0:
                                start = _signed_varint(pval)
                            elif pf == 2 and pw == 0:
                                end = _signed_varint(pval)
                        periods.append((start, end))
                    elif af == 5 and aw == 2:
                        for inf_f, inf_w, inf_v in _iter_fields(aval):
                            if inf_f == 2 and inf_w == 2:
                                routes.add(inf_v.decode("utf-8", "ignore"))
                            elif inf_f == 5 and inf_w == 2:
                                stops.add(inf_v.decode("utf-8", "ignore"))
                    elif af == 10 and aw == 2 and not header:
                        header = _parse_translated_string(aval)

                if not header:
                    continue
                if periods and not any(st <= now_ts <= en for st, en in periods):
                    continue
                route_match = not route_filter or (route_filter in routes)
                stop_match = bool(stop_ids and (stops & stop_ids))
                if (route_match and routes) or stop_match:
                    if header not in seen_alerts:
                        seen_alerts.add(header)
                        alerts.append(header)

    for sid in arrivals:
        arrivals[sid].sort(key=lambda item: item["time"])

    return {"arrivals": arrivals, "trip_updates": trip_updates, "alerts": alerts}


# ---------------------------------------------------------------------------
# Schedule Helpers (NYC Ferry Static GTFS)
# ---------------------------------------------------------------------------

def _parse_gtfs_time_seconds(hhmmss: str) -> int | None:
    parts = hhmmss.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        return h * 3600 + m * 60 + s
    except ValueError:
        return None


def _active_service_ids(z: zipfile.ZipFile, date_obj: datetime.date) -> set[str]:
    ymd = date_obj.strftime("%Y%m%d")
    weekday_col = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )[date_obj.weekday()]

    active: set[str] = set()
    if "calendar.txt" in z.namelist():
        for row in csv.DictReader(io.TextIOWrapper(z.open("calendar.txt"), encoding="utf-8-sig")):
            if row.get("start_date", "") <= ymd <= row.get("end_date", ""):
                if row.get(weekday_col) == "1":
                    active.add(row["service_id"])

    if "calendar_dates.txt" in z.namelist():
        for row in csv.DictReader(io.TextIOWrapper(z.open("calendar_dates.txt"), encoding="utf-8-sig")):
            if row.get("date") != ymd:
                continue
            sid = row["service_id"]
            if row.get("exception_type") == "1":
                active.add(sid)
            elif row.get("exception_type") == "2":
                active.discard(sid)
    return active


def _build_ferry_stop_schedule(raw_zip: bytes, stop_id: str = DEFAULT_FERRY_STOP_ID) -> dict[str, Any]:
    """Extract reusable schedule index for `stop_id` from NYC Ferry GTFS zip."""
    z = zipfile.ZipFile(io.BytesIO(raw_zip))
    trips: dict[str, dict[str, str]] = {}
    for row in csv.DictReader(io.TextIOWrapper(z.open("trips.txt"), encoding="utf-8-sig")):
        trips[row["trip_id"]] = {
            "route_id": row.get("route_id", ""),
            "service_id": row.get("service_id", ""),
            "headsign": row.get("trip_headsign", ""),
            "direction_id": row.get("direction_id", ""),
        }

    stop_times: list[dict[str, Any]] = []
    for row in csv.DictReader(io.TextIOWrapper(z.open("stop_times.txt"), encoding="utf-8-sig")):
        if row.get("stop_id") != stop_id:
            continue
        trip = trips.get(row.get("trip_id", ""))
        if not trip:
            continue
        sec = _parse_gtfs_time_seconds(row.get("departure_time") or row.get("arrival_time") or "")
        if sec is None:
            continue
        stop_times.append(
            {
                "trip_id": row["trip_id"],
                "sec": sec,
                **trip,
            }
        )

    calendar_rows = []
    if "calendar.txt" in z.namelist():
        calendar_rows = list(csv.DictReader(io.TextIOWrapper(z.open("calendar.txt"), encoding="utf-8-sig")))
    calendar_dates = []
    if "calendar_dates.txt" in z.namelist():
        calendar_dates = list(csv.DictReader(io.TextIOWrapper(z.open("calendar_dates.txt"), encoding="utf-8-sig")))

    return {
        "stop_times": stop_times,
        "calendar": calendar_rows,
        "calendar_dates": calendar_dates,
    }


def _active_services_from_index(index: dict[str, Any], date_obj: datetime.date) -> set[str]:
    ymd = date_obj.strftime("%Y%m%d")
    weekday_col = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )[date_obj.weekday()]

    active: set[str] = set()
    for row in index.get("calendar", []):
        if row.get("start_date", "") <= ymd <= row.get("end_date", "") and row.get(weekday_col) == "1":
            active.add(row["service_id"])
    for row in index.get("calendar_dates", []):
        if row.get("date") != ymd:
            continue
        sid = row["service_id"]
        if row.get("exception_type") == "1":
            active.add(sid)
        elif row.get("exception_type") == "2":
            active.discard(sid)
    return active


def _classify_status(count: int, low_threshold: int = 2) -> str:
    if count <= 0:
        return "empty"
    if count <= low_threshold:
        return "low"
    return "ok"


# ---------------------------------------------------------------------------
# Commute Driver
# ---------------------------------------------------------------------------

class CommuteDriver:
    """Async client aggregating MTA L train, NYC Ferry, Citi Bike, and Open-Meteo."""

    def __init__(
        self,
        lat: float = DEFAULT_LAT,
        lon: float = DEFAULT_LON,
        walk_minutes: int = DEFAULT_WALK_MINUTES,
        citibike_stations: list[str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.lat = lat
        self.lon = lon
        self.walk_minutes = walk_minutes
        self.citibike_stations = citibike_stations or list(DEFAULT_CITIBIKE_STATIONS)
        self._external_client = client is not None
        self._client = client

        self._citibike_info_cache: dict[str, dict[str, Any]] = {}
        self._citibike_info_ts: float = 0.0
        self._ferry_index: dict[str, Any] | None = None
        self._ferry_index_ts: float = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": "RemoteSmartHome/1.0"},
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._external_client:
            await self._client.aclose()
            self._client = None

    async def fetch_mta_l_train(self, now: float | None = None) -> dict[str, Any]:
        now_ts = time.time() if now is None else now
        client = await self._get_client()

        feed_resp = await client.get(MTA_L_FEED_URL)
        feed_resp.raise_for_status()

        parsed = parse_gtfs_rt(
            feed_resp.content,
            stop_ids={"L08N", "L08S"},
            route_filter="L",
            now=now_ts,
        )

        alerts: list[str] = list(parsed["alerts"])
        try:
            alerts_resp = await client.get(MTA_ALERTS_URL)
            if alerts_resp.status_code == 200:
                alerts_parsed = parse_gtfs_rt(
                    alerts_resp.content,
                    stop_ids={"L08", "L08N", "L08S"},
                    route_filter="L",
                    now=now_ts,
                )
                for text in alerts_parsed["alerts"]:
                    if text not in alerts:
                        alerts.append(text)
        except Exception as e:
            log.debug("MTA alerts fetch failed: %s", e)

        def fmt_direction(stop_id: str) -> list[dict[str, Any]]:
            items = []
            for entry in parsed["arrivals"].get(stop_id, [])[:4]:
                mins = int(entry["minutes"])
                items.append(
                    {
                        "minutes": mins,
                        "reachable": mins >= self.walk_minutes,
                    }
                )
            return items

        return {
            "line": "L",
            "station": "Bedford Av",
            "walk_minutes": self.walk_minutes,
            "manhattan": fmt_direction("L08N"),
            "brooklyn": fmt_direction("L08S"),
            "alerts": alerts[:3],
        }

    async def _ensure_ferry_index(self) -> dict[str, Any]:
        if self._ferry_index is not None and (time.monotonic() - self._ferry_index_ts) < 43200:
            return self._ferry_index
        client = await self._get_client()
        resp = await client.get(FERRY_GTFS_URL)
        resp.raise_for_status()
        self._ferry_index = _build_ferry_stop_schedule(resp.content, stop_id=DEFAULT_FERRY_STOP_ID)
        self._ferry_index_ts = time.monotonic()
        return self._ferry_index

    async def fetch_nyc_ferry(self, now: float | None = None) -> dict[str, Any]:
        now_ts = time.time() if now is None else now
        index = await self._ensure_ferry_index()

        rt_updates: dict[str, dict[str, dict[str, Any]]] = {}
        try:
            client = await self._get_client()
            rt_resp = await client.get(FERRY_RT_URL)
            if rt_resp.status_code == 200:
                rt_parsed = parse_gtfs_rt(
                    rt_resp.content,
                    stop_ids={DEFAULT_FERRY_STOP_ID},
                    now=now_ts,
                )
                rt_updates = rt_parsed["trip_updates"]
        except Exception as e:
            log.debug("NYC Ferry GTFS-RT fetch failed: %s", e)

        now_dt = datetime.datetime.fromtimestamp(now_ts, tz=NY_TZ)
        today = now_dt.date()
        active_today = _active_services_from_index(index, today)
        midnight_today = datetime.datetime.combine(today, datetime.time.min, tzinfo=NY_TZ).timestamp()

        southbound: list[dict[str, Any]] = []
        northbound: list[dict[str, Any]] = []

        for st in index["stop_times"]:
            if st["service_id"] not in active_today:
                continue
            sched_ts = midnight_today + st["sec"]
            trip_rt = rt_updates.get(st["trip_id"], {})
            stop_rt = trip_rt.get(DEFAULT_FERRY_STOP_ID, {})
            realtime = False
            dep_ts = sched_ts
            if stop_rt.get("time"):
                dep_ts = float(stop_rt["time"])
                realtime = True
            elif stop_rt.get("delay") is not None:
                dep_ts = sched_ts + float(stop_rt["delay"])
                realtime = True

            if dep_ts < now_ts - 30 or dep_ts > now_ts + 4 * 3600:
                continue

            mins = max(0, round((dep_ts - now_ts) / 60.0))
            dep_dt = datetime.datetime.fromtimestamp(dep_ts, tz=NY_TZ)
            entry = {
                "minutes": mins,
                "time_str": dep_dt.strftime("%-I:%M %p"),
                "realtime": realtime,
                "ts": dep_ts,
            }
            headsign = (st.get("headsign") or "").lower()
            if st.get("direction_id") == "0" or "wall" in headsign or "pier 11" in headsign:
                southbound.append(entry)
            else:
                northbound.append(entry)

        southbound.sort(key=lambda x: x["ts"])
        northbound.sort(key=lambda x: x["ts"])
        for lst in (southbound, northbound):
            for item in lst:
                item.pop("ts", None)

        return {
            "landing": "North Williamsburg",
            "route": "East River",
            "southbound": southbound[:3],
            "northbound": northbound[:3],
        }

    async def _ensure_citibike_info(self) -> dict[str, dict[str, Any]]:
        if self._citibike_info_cache and (time.monotonic() - self._citibike_info_ts) < 3600:
            return self._citibike_info_cache
        client = await self._get_client()
        resp = await client.get(CITIBIKE_INFO_URL)
        resp.raise_for_status()
        stations = resp.json().get("data", {}).get("stations", [])
        self._citibike_info_cache = {s["station_id"]: s for s in stations if "station_id" in s}
        self._citibike_info_ts = time.monotonic()
        return self._citibike_info_cache

    async def fetch_citibike(self) -> dict[str, Any]:
        info_map = await self._ensure_citibike_info()
        client = await self._get_client()
        resp = await client.get(CITIBIKE_STATUS_URL)
        resp.raise_for_status()
        status_list = resp.json().get("data", {}).get("stations", [])
        status_map = {s["station_id"]: s for s in status_list if "station_id" in s}

        stations_out: list[dict[str, Any]] = []
        for sid in self.citibike_stations:
            st = status_map.get(sid)
            if not st:
                continue
            info = info_map.get(sid, {})
            total_bikes = int(st.get("num_bikes_available", 0) or 0)
            ebikes = int(st.get("num_ebikes_available", 0) or 0)
            classic = max(0, total_bikes - ebikes)
            docks = int(st.get("num_docks_available", 0) or 0)
            renting = bool(st.get("is_renting", 1))
            returning = bool(st.get("is_returning", 1))
            stations_out.append(
                {
                    "id": sid,
                    "name": info.get("name") or sid,
                    "ebikes": ebikes,
                    "classic": classic,
                    "total_bikes": total_bikes,
                    "docks": docks,
                    "renting": renting,
                    "returning": returning,
                    "bike_status": _classify_status(total_bikes if renting else 0),
                    "dock_status": _classify_status(docks if returning else 0),
                }
            )
        return {"stations": stations_out}

    async def fetch_weather(self) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.get(
            OPEN_METEO_URL,
            params={
                "latitude": self.lat,
                "longitude": self.lon,
                "current": "temperature_2m,apparent_temperature,weather_code,precipitation,wind_speed_10m",
                "hourly": "precipitation_probability,temperature_2m,weather_code",
                "daily": "sunrise,sunset",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "America/New_York",
                "forecast_days": 2,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        cur = data.get("current", {})
        hourly = data.get("hourly", {})
        daily = data.get("daily", {})

        temp_f = round(float(cur.get("temperature_2m", 0)))
        feels_f = round(float(cur.get("apparent_temperature", temp_f)))
        code = int(cur.get("weather_code", 0))
        wind_mph = round(float(cur.get("wind_speed_10m", 0)))
        precip_mm = float(cur.get("precipitation", 0) or 0)
        condition, icon = WMO_CODES.get(code, ("Fair", "🌤️"))

        # Find current hour offset for next-6h precipitation lookahead
        cur_time = str(cur.get("time", ""))[:13]
        times = hourly.get("time", [])
        probs = hourly.get("precipitation_probability", [])
        start_idx = 0
        for idx, t in enumerate(times):
            if str(t)[:13] >= cur_time:
                start_idx = idx
                break

        next_6_probs = probs[start_idx + 1 : start_idx + 7]
        max_prob = max((int(p or 0) for p in next_6_probs), default=0)
        rain_eta_h = next((i + 1 for i, p in enumerate(next_6_probs) if int(p or 0) >= 50), None)

        if precip_mm > 0 or code in (51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99):
            headline = f"{condition} now · {temp_f}°F (feels {feels_f}°)"
        elif rain_eta_h is not None:
            headline = f"Rain likely in ~{rain_eta_h}h ({max_prob}%)"
        else:
            headline = f"Feels like {feels_f}° · {condition}"

        sunset_str = ""
        sunsets = daily.get("sunset", [])
        if sunsets:
            try:
                dt = datetime.datetime.fromisoformat(sunsets[0])
                sunset_str = dt.strftime("%-I:%M %p")
            except Exception:
                pass

        return {
            "temp_f": temp_f,
            "feels_like_f": feels_f,
            "condition": condition,
            "icon": icon,
            "wind_mph": wind_mph,
            "sunset": sunset_str,
            "precip_prob_next_6h": max_prob,
            "headline": headline,
        }
