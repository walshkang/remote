"""Denon AVR-X1200W driver.
Maintains an async Telnet connection on port 23 with automatic HTTP port 80 fallback,
keep-alive heartbeat, safe MVMAX volume parsing, and NSE Now-Playing metadata extraction.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Awaitable, Callable
import xml.etree.ElementTree as ET

import httpx

log = logging.getLogger(__name__)


class DenonDriver:
    def __init__(
        self,
        host: str,
        on_state_change: Callable[[dict[str, Any]], Awaitable[None]],
        telnet_port: int = 23,
        http_port: int = 80,
    ) -> None:
        self.host = host
        self.telnet_port = telnet_port
        self.http_port = http_port
        self.on_state_change = on_state_change

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._loop_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._running = False
        self._telnet_connected = False

        self._now_playing_lines: dict[int, str] = {}

    async def start(self) -> None:
        self._running = True
        self._loop_task = asyncio.create_task(self._connection_loop())

    async def stop(self) -> None:
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._loop_task:
            self._loop_task.cancel()
        await self._close_socket()

    async def _close_socket(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None
        if self._telnet_connected:
            self._telnet_connected = False
            await self.on_state_change({"connected": False})

    async def _connection_loop(self) -> None:
        """Continuously attempts Telnet connection with exponential backoff."""
        backoff = 2.0
        while self._running:
            try:
                log.info("Connecting to Denon AVR at %s:%d...", self.host, self.telnet_port)
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.telnet_port), timeout=5.0
                )
                self._telnet_connected = True
                backoff = 2.0
                log.info("Connected to Denon AVR at %s:%d", self.host, self.telnet_port)
                await self.on_state_change({"connected": True})

                # Start heartbeat
                if self._heartbeat_task:
                    self._heartbeat_task.cancel()
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                # Request initial status query
                await self.send_raw("PW?\r")
                await self.send_raw("MV?\r")
                await self.send_raw("MU?\r")
                await self.send_raw("SI?\r")
                await self.send_raw("NSE\r")

                # Fetch custom source renames and friendly name from HTTP XML API
                asyncio.create_task(self._refresh_source_config())

                # Read line stream
                while self._running:
                    line = await self._reader.readuntil(b"\r")
                    text = line.decode("ascii", errors="ignore").strip()
                    if text:
                        await self._parse_line(text)

            except (asyncio.CancelledError, GeneratorExit):
                break
            except Exception as e:
                log.warning("Denon telnet disconnected/error: %s. Retrying in %.1fs...", e, backoff)
                await self._close_socket()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 30.0)

    async def _heartbeat_loop(self) -> None:
        """Sends periodic queries so idle sockets don't time out, and refreshes Now Playing."""
        while self._running and self._telnet_connected:
            await asyncio.sleep(15.0)
            try:
                await self.send_raw("PW?\r")
                await self.send_raw("NSE\r")
            except Exception:
                break

    async def send_raw(self, cmd: str) -> None:
        """Sends a command via Telnet, falling back to HTTP GET if Telnet is offline."""
        if not cmd.endswith("\r"):
            cmd = cmd + "\r"

        if self._writer and self._telnet_connected:
            try:
                self._writer.write(cmd.encode("ascii"))
                await self._writer.drain()
                return
            except Exception as e:
                log.warning("Failed sending telnet command %r: %s", cmd, e)
                await self._close_socket()

        # Fallback to HTTP port 80
        await self._send_http(cmd.strip())

    async def _send_http(self, clean_cmd: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                url = f"http://{self.host}:{self.http_port}/goform/formiPhoneAppDirect.xml?{clean_cmd}"
                await client.get(url)
        except Exception as e:
            log.debug("HTTP fallback send failed: %s", e)

    async def _refresh_source_config(self) -> None:
        """Fetch friendly name and custom input source renames from Denon's HTTP XML API."""
        url = f"http://{self.host}:{self.http_port}/goform/formMainZone_MainZoneXmlStatus.xml"
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    root = ET.fromstring(resp.text)
                    funcs = [v.text.strip() for v in root.findall("./InputFuncList/value") if v.text]
                    renames = []
                    for v in root.findall("./RenameSource/value"):
                        sub = v.find("value")
                        text = (sub.text if sub is not None and sub.text else v.text) or ""
                        renames.append(text.strip())
                    deletes = [v.text.strip() if v.text else "USE" for v in root.findall("./SourceDelete/value")]

                    code_map = {
                        "Media Player": "MPLAY",
                        "TV AUDIO": "TV",
                        "CBL/SAT": "SAT/CBL",
                        "Bluetooth": "BT",
                        "NETWORK": "NET",
                        "AUX": "AUX1",
                        "iPod/USB": "USB/IPOD",
                        "Blu-ray": "BD",
                        "GAME": "GAME",
                        "DVD": "DVD",
                        "TUNER": "TUNER",
                    }

                    sources = []
                    for i, func in enumerate(funcs):
                        if i < len(deletes) and deletes[i] == "DEL":
                            continue
                        name = renames[i] if i < len(renames) and renames[i] else func
                        code = code_map.get(func, func)

                        icon = "🎵"
                        nl = name.lower()
                        if "turntable" in nl or "record" in nl or "phono" in nl or "vinyl" in nl:
                            icon = "🎛️"
                        elif "cd" in nl:
                            icon = "💿"
                        elif "tv" in nl:
                            icon = "🔊"
                        elif "game" in nl or "ps5" in nl or "xbox" in nl:
                            icon = "🎮"
                        elif "aux" in nl:
                            icon = "🔌"
                        elif "bluetooth" in nl or code == "BT":
                            icon = "ᛒ"
                        elif "online" in nl or "net" in nl or code == "NET":
                            icon = "🌐"
                        elif "apple" in nl:
                            icon = "📺"

                        sources.append({"code": code, "name": name, "icon": icon, "func": func})

                    zone_el = root.find("./Zone/value")
                    zone_name = zone_el.text.strip() if zone_el is not None and zone_el.text else ""

                    patch = {"sources": sources}
                    if zone_name:
                        patch["zone_name"] = zone_name
                    await self.on_state_change(patch)
        except Exception as e:
            log.debug("Failed fetching Denon source renames from HTTP: %s", e)

    async def _parse_line(self, line: str) -> None:
        """Parses a single response line from Denon AVR."""
        # 1. Power
        if line == "PWON":
            await self.on_state_change({"power": "ON"})
        elif line == "PWSTANDBY":
            await self.on_state_change({"power": "STANDBY"})

        # 2. Mute
        elif line == "MUON":
            await self.on_state_change({"mute": True})
        elif line == "MUOFF":
            await self.on_state_change({"mute": False})

        # 3. Master Volume (filter out MVMAX)
        elif line.startswith("MV") and not line.startswith("MVMAX"):
            vol_str = line[2:]
            # Denon volume can be 2 digits (e.g. '50') or 3 digits (e.g. '505' for 50.5)
            if re.match(r"^\d{2,3}$", vol_str):
                if len(vol_str) == 3:
                    val = float(vol_str[:2]) + 0.5
                else:
                    val = float(vol_str)

                # Relative dB calculation: 80 is 0.0dB
                rel_db = val - 80.0
                db_display = f"{rel_db:+.1f} dB" if rel_db != 0 else "0.0 dB"
                await self.on_state_change({
                    "volume": val,
                    "volume_db": db_display
                })

        # 4. Source Input
        elif line.startswith("SI"):
            source = line[2:]
            await self.on_state_change({"source": source})

        # 5. On-Screen Display / Now Playing (NSE0 through NSE8)
        elif line.startswith("NSE") and len(line) >= 4 and line[3].isdigit():
            idx = int(line[3])
            content = line[4:].strip()
            self._now_playing_lines[idx] = content

            # NSE1 is usually Track, NSE2 is Artist, NSE4 is Album (on Spotify/AirPlay)
            track = self._now_playing_lines.get(1, "")
            artist = self._now_playing_lines.get(2, "")
            album = self._now_playing_lines.get(4, "")
            await self.on_state_change({
                "now_playing": {
                    "track": track,
                    "artist": artist,
                    "album": album
                }
            })
