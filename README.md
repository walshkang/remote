# Remote 📱🏠

A unified local-first smart home remote control web app designed for anyone on your local Wi-Fi.

## Targets & Integrations

- 💡 **Philips Hue**: Direct local LAN control via Hue Bridge (CLIP v2 REST API / SSE).
- 🔊 **Denon AVR**: Instant LAN control via Denon Telnet (port 23) or HTTP API (port 8080/80) for volume, power, inputs, and sound modes.
- 🐱 **Petlibro Smart Feeder**: Cloud API / Tuya integration for manual snack dispenses and food level telemetry.
- 🤖 **Litter-Robot 4 (Whisker)**: Whisker API for waste drawer levels, clean cycle triggering, cat visit stats, and status.
- 📦 **BuildingLink**: Resident API (`eventlog-us1.buildinglink.com`) for live front-desk package & delivery tracking.
- 🚇 **Going Out & Commute (Roadmap)**: Bedford Ave (L train) MTA arrivals, North Williamsburg Citi Bike availability, and hyperlocal weather.

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

## Production Deployment

The app is deployed to an Oracle Cloud Always Free VM behind Caddy with automatic SSL:
* **Live URL**: `https://remote.walshkang.com`
* **Security**: Whitelisted to Home Wi-Fi (`HOME_IP`) and Tailscale (`100.64.0.0/10`).
* **Deployment Guide**: See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for step-by-step setup (DNS, Oracle firewalls, Caddy, and router port forwarding).

## Setup & Local Development

Requires [uv](https://docs.astral.sh/uv/) (it provisions Python 3.12 automatically).

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
uv run pytest
```

Then open `http://localhost:8000`. Keep `--workers 1`: device connections (e.g. the Denon's single Telnet slot) are singletons.

Modules are configured via `.env` and enabled with `REMOTE_MODULES` (comma-separated, default `demo`). See [docs/ARCHITECTURE_AND_PLAN.md](docs/ARCHITECTURE_AND_PLAN.md).

