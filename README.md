# Remote 📱🏠

A unified local-first smart home remote control web app designed for anyone on your local Wi-Fi.

## Targets & Integrations

- 💡 **Philips Hue**: Direct local LAN control via Hue Bridge (CLIP v2 REST API / SSE).
- 🔊 **Denon AVR**: Instant LAN control via Denon Telnet (port 23) or HTTP API (port 8080/80) for volume, power, inputs, and sound modes.
- 🐱 **Petlibro Smart Feeder**: Cloud API / Tuya integration for manual snack dispenses and food level telemetry.
- 🤖 **Litter-Robot 4 (Whisker)**: Whisker API for waste drawer levels, clean cycle triggering, cat visit stats, and status.

## Architecture

```
                 [ Any Phone / Tablet / Laptop on Wi-Fi ]
                                    │
                                    ▼ (HTTP / WebSockets)
             ┌──────────────────────────────────────────────┐
             │            Remote Web Server (LAN)           │
             │           FastAPI / Node.js Backend          │
             │        Responsive Touch Dashboard (PWA)      │
             └───────┬──────────────┬─────────────┬─────────┘
                     │ LAN          │ LAN         │ Cloud
                     ▼              ▼             ▼
               [Hue Bridge]   [Denon AVR]   [Whisker & Petlibro]
                     │              │             │
                 Lights        Audio/Home       Feeder &
                                 Theater      Litter-Robot
```

## Setup & Development

Requires [uv](https://docs.astral.sh/uv/) (it provisions Python 3.12 automatically).

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
uv run pytest
```

Then open `http://<this-machine-ip>:8000` on any device on the same Wi-Fi. Keep `--workers 1`: device connections (e.g. the Denon's single Telnet slot) are singletons.

Modules are enabled with `REMOTE_MODULES` (comma-separated, default `demo`). See [docs/ARCHITECTURE_AND_PLAN.md](docs/ARCHITECTURE_AND_PLAN.md).
