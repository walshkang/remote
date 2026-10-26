"""Async driver for BuildingLink Resident API (eventlog-us1 & auth.buildinglink.com)."""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

EVENTLOG_URL = "https://eventlog-us1.buildinglink.com/event-log/resident"
TOKEN_URL = "https://auth.buildinglink.com/connect/token"
LOGIN_URL = "https://auth.buildinglink.com/account/login"
DEFAULT_API_KEY = "hylwvvmjdgc45mt9kab1agriyvuh0nig9qx8djmu"
CLIENT_ID = "vue-app"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15"
)


def decode_jwt_claims(token: str) -> dict[str, Any]:
    """Decode JWT payload claims without requiring verification keys."""
    if not token or "." not in token:
        return {}
    parts = token.strip().split(".")
    if len(parts) < 2:
        return {}
    payload_b64 = parts[1]
    pad = "=" * ((4 - len(payload_b64) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload_b64 + pad)
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def extract_token_input(raw: str) -> dict[str, Any]:
    """Parse a user-provided token string, 'Bearer ...' header, cURL snippet, or bl.application JSON."""
    text = raw.strip()
    if not text:
        raise ValueError("Empty token input")

    # Case 1: JSON object from localStorage `bl.application` or token response
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            access = (
                obj.get("accessToken")
                or obj.get("access_token")
                or (obj.get("user") or {}).get("access_token")
                or ""
            )
            refresh = obj.get("refreshToken") or obj.get("refresh_token") or ""
            user_info = obj.get("user") if isinstance(obj.get("user"), dict) else {}
            if access:
                claims = {**decode_jwt_claims(access), **user_info}
                return {
                    "access_token": access.strip(),
                    "refresh_token": refresh.strip(),
                    "claims": claims,
                }
        except json.JSONDecodeError:
            pass

    # Case 2: cURL snippet or Bearer header containing a JWT
    jwt_match = re.search(r"(eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)", text)
    if jwt_match:
        access = jwt_match.group(1)
        return {
            "access_token": access,
            "refresh_token": "",
            "claims": decode_jwt_claims(access),
        }

    # Case 3: Plain token string
    if text.lower().startswith("bearer "):
        text = text[7:].strip()
    return {
        "access_token": text,
        "refresh_token": "",
        "claims": decode_jwt_claims(text),
    }


import datetime
from zoneinfo import ZoneInfo

def parse_delivery(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw BuildingLink event-log entry into a clean frontend model."""
    item_id = str(
        item.get("id")
        or item.get("eventId")
        or item.get("EventId")
        or item.get("Id")
        or item.get("trackingNumber")
        or ""
    )

    carrier_raw = (
        item.get("carrier")
        or item.get("carrierName")
        or item.get("CarrierName")
        or item.get("eventTypeName")
        or item.get("vendor")
        or item.get("sender")
        or item.get("shippingCompany")
        or item.get("typeDescription")
        or item.get("eventTypeDescription")
        or "Package"
    )
    carrier = str(carrier_raw).strip()
    c_upper = carrier.upper()
    if c_upper in ("AMAZON", "AMZN"):
        carrier = "Amazon"
    elif c_upper in ("FEDEX", "FED EX"):
        carrier = "FedEx"
    elif c_upper in ("UPS", "USPS", "DHL"):
        carrier = c_upper
    elif carrier.isupper() and len(carrier) > 4:
        carrier = carrier.title()

    pkg_type = str(
        item.get("type")
        or item.get("eventType")
        or item.get("typeDescription")
        or item.get("packageType")
        or "Delivery"
    ).strip()

    description = str(
        item.get("comment")
        or item.get("comments")
        or item.get("openComment")
        or item.get("description")
        or item.get("notes")
        or ""
    ).strip()

    tracking = str(
        item.get("trackingNumber")
        or item.get("TrackingNumber")
        or item.get("tracking")
        or item.get("barcode")
        or ""
    ).strip()

    if not tracking and description:
        tba_match = re.search(r"(TBA[0-9]{10,}|1Z[A-Z0-9]{16}|[0-9]{20,22})", description)
        if tba_match:
            tracking = tba_match.group(1)

    received_raw = str(
        item.get("openUtc")
        or item.get("openDate")
        or item.get("openTime")
        or item.get("createdDate")
        or item.get("createDate")
        or item.get("receivedAt")
        or item.get("timestamp")
        or item.get("date")
        or ""
    ).strip()

    received_at = received_raw
    if "T" in received_raw and ("Z" in received_raw or "+" in received_raw):
        try:
            clean_iso = received_raw.rstrip("Z").split(".")[0]
            utc_dt = datetime.datetime.fromisoformat(clean_iso).replace(tzinfo=datetime.timezone.utc)
            ny_tz = ZoneInfo("America/New_York")
            ny_dt = utc_dt.astimezone(ny_tz)
            now_ny = datetime.datetime.now(ny_tz)
            if ny_dt.date() == now_ny.date():
                received_at = f"Today {ny_dt.strftime('%-I:%M %p')}"
            else:
                received_at = ny_dt.strftime("%b %-d, %-I:%M %p")
        except Exception:
            pass

    location = str(
        item.get("location")
        or item.get("storageLocation")
        or item.get("packageLocation")
        or "Front Desk"
    ).strip()

    icon_url = str(item.get("iconBlobUrl") or "").strip()

    return {
        "id": item_id,
        "carrier": carrier,
        "type": pkg_type,
        "tracking": tracking,
        "description": description,
        "received_at": received_at,
        "location": location,
        "icon_url": icon_url,
    }


class BuildingLinkAuthError(RuntimeError):
    """Raised when the access token is expired or rejected (HTTP 401/403)."""


class BuildingLinkDriver:
    """Async client for BuildingLink's Resident EventLog & Identity endpoints."""

    def __init__(
        self,
        access_token: str = "",
        refresh_token: str = "",
        api_key: str = DEFAULT_API_KEY,
        username: str = "",
        password: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.access_token = access_token.strip()
        self.refresh_token = refresh_token.strip()
        self.api_key = (api_key or DEFAULT_API_KEY).strip()
        self.username = username.strip()
        self.password = password
        self._external_client = client is not None
        self._client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0, headers={"User-Agent": USER_AGENT})
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._external_client:
            await self._client.aclose()
            self._client = None

    def token_claims(self) -> dict[str, Any]:
        return decode_jwt_claims(self.access_token)

    def is_token_expired(self, leeway_s: float = 30.0) -> bool:
        claims = self.token_claims()
        exp = claims.get("exp")
        if not exp:
            return not bool(self.access_token)
        return time.time() + leeway_s >= float(exp)

    async def refresh_access_token(self) -> bool:
        """Attempt to renew access_token using refresh_token against auth.buildinglink.com."""
        if not self.refresh_token:
            return False
        client = await self._get_client()
        try:
            resp = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": CLIENT_ID,
                    "refresh_token": self.refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code == 200:
                data = resp.json()
                new_access = data.get("access_token")
                if new_access:
                    self.access_token = new_access
                    if data.get("refresh_token"):
                        self.refresh_token = data["refresh_token"]
                    return True
            log.warning("BuildingLink token refresh returned %s: %s", resp.status_code, resp.text)
        except Exception as e:
            log.warning("BuildingLink token refresh error: %s", e)
        return False

    async def fetch_deliveries(self) -> list[dict[str, Any]]:
        """Query open resident deliveries from eventlog-us1.buildinglink.com."""
        if not self.access_token:
            raise BuildingLinkAuthError("No BuildingLink access token configured")

        if self.is_token_expired() and self.refresh_token:
            await self.refresh_access_token()

        client = await self._get_client()
        headers = {
            "Accept": "application/json; odata.metadata=minimal; odata.streaming=true",
            "Authorization": f"Bearer {self.access_token}",
            "X-API-Key": self.api_key,
            "Origin": "https://2northsidepiersresidents.buildinglink.com",
            "Referer": "https://2northsidepiersresidents.buildinglink.com/",
        }
        resp = await client.get(EVENTLOG_URL, headers=headers)

        if resp.status_code in (401, 403):
            if self.refresh_token and await self.refresh_access_token():
                headers["Authorization"] = f"Bearer {self.access_token}"
                resp = await client.get(EVENTLOG_URL, headers=headers)

        if resp.status_code in (401, 403):
            raise BuildingLinkAuthError("Session token expired — paste a fresh token to reconnect")

        resp.raise_for_status()
        payload = resp.json()

        raw_items: list[Any]
        if isinstance(payload, list):
            raw_items = payload
        elif isinstance(payload, dict):
            raw_items = payload.get("value") or payload.get("items") or payload.get("data") or []
        else:
            raw_items = []

        return [parse_delivery(item) for item in raw_items if isinstance(item, dict)]
