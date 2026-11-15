"""Async driver for Petlibro Cloud API (api.us.petlibro.com)."""
from __future__ import annotations

import datetime
import hashlib
import logging
import uuid
from typing import Any
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://api.us.petlibro.com"
APP_ID = 1
APP_SN = "c35772530d1041699c87fe62348507a8"
TIMEZONE = "America/New_York"
NY_TZ = ZoneInfo(TIMEZONE)


class PetlibroAuthError(RuntimeError):
    """Raised when Petlibro rejects login credentials or session token."""


def normalize_feeder(device: dict[str, Any], info: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize Petlibro device + realInfo payloads into a clean frontend model."""
    merged = {**device, **(info or {})}
    sn = str(merged.get("deviceSn") or merged.get("id") or "")
    name = str(merged.get("name") or merged.get("deviceName") or "Granary Feeder").strip()
    online = bool(merged.get("online", False))

    grain_raw = merged.get("grainStatus")
    if grain_raw is None:
        grain_raw = merged.get("foodStatus")
    surplus = merged.get("surplusGrain")

    if grain_raw in (2, "EMPTY", "empty") or surplus is False:
        food_status = "Empty"
        food_ok = False
    elif grain_raw in (1, "LOW", "low"):
        food_status = "Low"
        food_ok = False
    else:
        food_status = "Full"
        food_ok = True

    battery_raw = merged.get("electricQuantity")
    if battery_raw is None:
        battery_raw = merged.get("batteryPercentage")
    battery_pct = int(battery_raw) if isinstance(battery_raw, (int, float)) else None

    power_type = merged.get("powerType")
    if power_type == 2:
        power_mode = "Battery"
    elif power_type == 1:
        power_mode = "AC Power"
    elif battery_pct is not None and battery_pct < 100:
        power_mode = f"Battery ({battery_pct}%)"
    else:
        power_mode = "AC Power"

    today_portions = int(
        merged.get("todayFeedingQuantity")
        or merged.get("todayFeedCount")
        or merged.get("todayPortions")
        or 0
    )

    last_fed = ""
    last_ts = merged.get("lastFeedingTime") or merged.get("lastFeedTime")
    if isinstance(last_ts, (int, float)) and last_ts > 0:
        ts_s = last_ts / 1000.0 if last_ts > 1e11 else float(last_ts)
        last_fed = datetime.datetime.fromtimestamp(ts_s, tz=NY_TZ).strftime("%-I:%M %p")
    elif isinstance(last_ts, str) and last_ts.strip():
        last_fed = last_ts.strip()

    return {
        "sn": sn,
        "name": name,
        "online": online,
        "food_status": food_status,
        "food_ok": food_ok,
        "battery_pct": battery_pct,
        "power_mode": power_mode,
        "today_portions": today_portions,
        "last_fed": last_fed,
    }


class PetlibroDriver:
    """Async HTTP client for Petlibro Granary feeders."""

    def __init__(
        self,
        email: str = "",
        password: str = "",
        token: str = "",
        base_url: str = BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.email = email.strip()
        self.password = password
        self.token = token.strip()
        self.base_url = base_url.rstrip("/")
        self._external_client = client is not None
        self._client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._external_client:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "source": "ANDROID",
            "language": "EN",
            "timezone": TIMEZONE,
            "version": "1.3.45",
            "Content-Type": "application/json",
        }
        if self.token:
            headers["token"] = self.token
        return headers

    async def login(self) -> str:
        """Authenticate using email + MD5(password) to acquire a session token."""
        if not (self.email and self.password):
            raise PetlibroAuthError("Petlibro email and password are required")

        client = await self._get_client()
        pwd_md5 = hashlib.md5(self.password.encode("utf-8")).hexdigest()
        resp = await client.post(
            f"{self.base_url}/member/auth/login",
            headers=self._headers(),
            json={
                "appId": APP_ID,
                "appSn": APP_SN,
                "country": "US",
                "email": self.email,
                "password": pwd_md5,
                "phoneBrand": "",
                "phoneSystemVersion": "",
                "timezone": TIMEZONE,
                "thirdId": None,
                "type": None,
            },
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != 0:
            raise PetlibroAuthError(body.get("msg") or "Petlibro login rejected")
        token = str((body.get("data") or {}).get("token") or "").strip()
        if not token:
            raise PetlibroAuthError("Petlibro login response contained no token")
        self.token = token
        return token

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        if not self.token:
            await self.login()
        client = await self._get_client()

        for attempt in range(2):
            resp = await client.post(
                f"{self.base_url}{path}",
                headers=self._headers(),
                json=payload,
            )
            if resp.status_code in (401, 403):
                if attempt == 0 and self.email and self.password:
                    await self.login()
                    continue
                raise PetlibroAuthError("Petlibro session expired")
            resp.raise_for_status()
            body = resp.json()
            code = body.get("code")
            if code in (1002, 1009):  # invalid/expired token codes
                if attempt == 0 and self.email and self.password:
                    await self.login()
                    continue
                raise PetlibroAuthError(body.get("msg") or "Petlibro token expired")
            if code != 0:
                raise RuntimeError(body.get("msg") or f"Petlibro API error (code {code})")
            return body.get("data")
        raise PetlibroAuthError("Petlibro authentication failed")

    async def list_devices(self) -> list[dict[str, Any]]:
        data = await self._post("/device/device/list", {})
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        return []

    async def fetch_real_info(self, device_sn: str) -> dict[str, Any]:
        data = await self._post("/device/device/realInfo", {"id": device_sn, "deviceSn": device_sn})
        return data if isinstance(data, dict) else {}

    async def fetch_feeder_snapshot(self) -> dict[str, Any]:
        devices = await self.list_devices()
        if not devices:
            raise RuntimeError("No Petlibro devices found on this account")
        feeder = devices[0]
        sn = str(feeder.get("deviceSn") or feeder.get("id") or "")
        info: dict[str, Any] = {}
        if sn:
            try:
                info = await self.fetch_real_info(sn)
            except Exception as e:
                log.debug("Petlibro realInfo fetch failed for %s: %s", sn, e)
        return normalize_feeder(feeder, info)

    async def manual_feed(self, device_sn: str, portions: int = 1) -> dict[str, Any]:
        qty = max(1, min(5, int(portions)))
        data = await self._post(
            "/device/device/manualFeeding",
            {
                "deviceSn": device_sn,
                "grainNum": qty,
                "requestId": uuid.uuid4().hex,
            },
        )
        return data if isinstance(data, dict) else {"portions": qty}
