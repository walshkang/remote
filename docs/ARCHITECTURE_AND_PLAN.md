# 🏗️ Engineering Plan: 'Remote' Local Smart Home Web App

> **Status:** Ready for Agent Critique & Build  
> **Target Devices:** Denon AVR-X1200W, Philips Hue Bridge, Petlibro Granary Feeder, Whisker Litter-Robot 4  
> **Target Access:** Mobile devices on local Wi-Fi via custom domain or local IP.

---

## 1. Executive Summary & Goals

A unified, mobile-first web remote control accessible to anyone connected to the home Wi-Fi.

### Core Targets
1. **Denon AVR-X1200W**: Instant volume control, mute, power toggle, and input source switching (Apple TV, TV Audio, Media Player, etc.).
2. **Philips Hue**: Room & zone controls, brightness, color temperature, and scene activation.
3. **Petlibro Granary**: 1-tap manual snack dispense, food tank status, and battery telemetry.
4. **Litter-Robot 4**: Live waste drawer fill percentage, cycle status, "Clean Now" trigger, and cat visit stats.
5. **Network / Domain Access**: Accessible via a custom domain (e.g. `remote.userdomain.com`) restricted strictly to visitors on the home Wi-Fi, without requiring mobile apps or App Store downloads.
6. **Live Multi-Device State Sync**: Bidirectional WebSockets so any adjustment made physically or from another phone updates all active clients immediately.

---

## 2. Network Topology & Domain Strategy

### The Challenge
Browsers enforce **Private Network Access (PNA)** and **Mixed Content blocking**: a public HTTPS webpage cannot directly issue fetch requests to unencrypted private IP addresses (`192.168.x.x`). External cloud servers (Vercel/AWS) cannot reach local private IPs without an active bridge.

### Evaluated Approaches
1. **Option A: Local Split DNS / Subdomain Mapping (Recommended Baseline)**:
   - Create a DNS `A` record: `remote.userdomain.com -> 192.168.1.X` (local server IP).
   - Only resolves when client is on the home Wi-Fi subnet. Outside visitors time out cleanly.
2. **Option B: Cloudflare Tunnel with Source IP Filtering**:
   - Run `cloudflared` on host machine.
   - Configure Cloudflare Zero Trust policy: *"Allow only requests from `<Home_Public_IP>`"*.
   - Free SSL termination and remote access capability if authenticated.

---

## 3. System Architecture & Tech Stack

```
┌─────────────────────────────────────────────────────────────┐
│                    Client Browser (PWA)                     │
│  - Tailwind CSS + Mobile Touch UI (Large thumb zones)       │
│  - WebSocket client for sub-50ms reactive state updates     │
│  - Offline ServiceWorker shell + Web App Manifest           │
└──────────────────────────────▲──────────────────────────────┘
                               │ WebSocket / REST
┌──────────────────────────────▼──────────────────────────────┐
│                    FastAPI Server (Python 3.8+)             │
│                                                             │
│  ┌───────────────────┐  ┌───────────────────┐  ┌─────────┐  │
│  │   State Manager   │  │  WebSocket PubSub │  │ FastAPI │  │
│  │  (In-Memory Cache)│  │   (Realtime Hub)  │  │ REST API│  │
│  └─────────┬─────────┘  └─────────┬─────────┘  └────┬────┘  │
│            │                      │                 │       │
│  ┌─────────▼──────────────────────▼─────────────────▼────┐  │
│  │                     Device Drivers                    │  │
│  │  ┌───────────────┐ ┌───────────────┐ ┌─────────────┐  │  │
│  │  │ DenonDriver   │ │ HueDriver     │ │ PetDriver   │  │  │
│  │  │ (Async Telnet)│ │ (CLIP v2 SSE) │ │ (Whisker/   │  │  │
│  │  │               │ │               │ │  Petlibro)  │  │  │
│  │  └───────────────┘ └───────────────┘ └─────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

* **Backend**: **Python (FastAPI + `asyncio`)**.
  - Asynchronous event loop handles persistent TCP socket for Denon AVR, Hue SSE stream, and Whisker/Petlibro background polling.
  - Python ecosystem provides existing reverse-engineered client packages (`pylitterbot`, `aiohue`, `denonavr`).
* **Frontend**: **Vanilla JS / Alpine.js + Tailwind CSS (PWA)**.
  - Zero build step bloat, instant local serving, zero latency.

---

## 4. Device Drivers & Protocols Deep Dive

### 4.1 Denon AVR-X1200W Driver
* **Protocol**: Denon AVR Telnet (TCP Port `23`).
* **Command Syntax**:
  - Volume Step: `MVUP\r`, `MVDOWN\r`
  - Exact Volume: `MV50\r` (corresponds to 50 / 80)
  - Mute: `MUON\r`, `MUOFF\r`, `MU?\r`
  - Power: `PWON\r`, `PWSTANDBY\r`, `PW?\r`
  - Source Selection: `SISAT/CBL\r`, `SIMEDIA\r`, `SIBD\r`, `SIGAME\r`, `SIAUX1\r`
* **Handling Connection Drops**: Keep-alive heartbeat (`PW?\r` every 30s) and automatic exponential backoff reconnection.

### 4.2 Philips Hue Bridge Driver
* **Protocol**: Hue Bridge REST API (v2 CLIP API) + Server-Sent Events (`/eventstream/clip/v2`).
* **Flow**:
  1. Auto-discover bridge via mDNS (`_hue._tcp.local`) or SSDP.
  2. First-time link: User presses physical bridge button; server sends `POST /api` to receive persistent `app_key`.
  3. Real-time updates: Subscribe to Hue SSE event stream; broadcast state changes to all connected WebSockets.

### 4.3 Petlibro Granary Feeder Driver
* **Protocol**: Petlibro Cloud API.
* **Authentication Gotcha**: Single active session limit.
  - *Fix*: Use a secondary Petlibro account (`user+remote@domain.com`) with the feeder shared to it.
* **Actions**: 1-portion snack trigger (`POST /feed`) and 5-min polling for tank level status (Normal / Low / Empty) and battery status.

### 4.4 Litter-Robot 4 (Whisker) Driver
* **Protocol**: Whisker AWS Cognito Auth + REST API (`pylitterbot`).
* **Telemetry & Actions**:
  - Waste drawer level percentage (`cat.drawer_percentage`).
  - Robot cycle status (`cat.status`: Ready, Cycling, Cat Detected).
  - Trigger clean cycle: `await robot.start_clean_cycle()`.

---

## 5. Phased Implementation Roadmap

### Phase 1: Local Backbone (Denon AVR-X1200W + Hue)
- [ ] Base FastAPI server and dependencies.
- [ ] `app/drivers/denon.py` with async TCP telnet socket, command queue, and volume parsing.
- [ ] `app/drivers/hue.py` with bridge discovery and light toggle/slider APIs.
- [ ] Mobile-first web interface with volume buttons, mute toggle, and light tiles.

### Phase 2: Cloud Pet Integrations (Petlibro + Litter-Robot)
- [ ] `app/drivers/litter_robot.py` via `pylitterbot` for waste drawer gauge & manual cycle.
- [ ] `app/drivers/petlibro.py` using secondary account credentials for snack triggers.
- [ ] Add "Pet Corner" card to the web UI.

### Phase 3: Domain Routing, Macros & PWA Polish
- [ ] PWA `manifest.json` and touch icons for "Add to Home Screen".
- [ ] Configure local DNS / Cloudflare Tunnel for `remote.userdomain.com`.
- [ ] 1-tap macro scenes (e.g. *Movie Night*, *Goodnight*).

### Phase 4: Neighborhood & Commute Telemetry ("Going Out")
- [ ] **MTA L Train Subway Arrivals (Bedford Av)**:
  - Real-time departure predictions for Bedford Ave (L line) via MTA GTFS-Realtime protobuf feed.
  - Manhattan-bound vs Canarsie-bound minute countdowns (e.g. `Manhattan: 3 · 8 · 14 min`).
  - Walking-time filter (e.g. "4 min walk to Bedford" to flag reachable vs unreachable trains).
  - High-priority service alert escalation banner for L train delays, suspensions, and planned track work.
- [ ] **Citi Bike Station Telemetry (North Williamsburg)**:
  - Real-time station capacity from Citi Bike GBFS feeds (`station_status.json`).
  - Target stations: N 6th & Bedford, Kent & N 5th, etc.
  - Dual-mode glance: "Take a bike" (standard + e-bike counts) vs "Return a bike" (empty dock counts).
  - Low-inventory color coding (green = plentiful, amber = 1-2 left, red = empty).
- [ ] **Hyperlocal Weather & Air Quality**:
  - Integration with Open-Meteo / NWS API.
  - Dynamic time-aware headline (e.g. "Rain starting in 40 min", "High 62° · jacket weather").
  - 1-tap detail view: hourly precipitation graph, sunset / golden hour timing, air quality index.
- [ ] **Ferry Departure Glance**:
  - NYC Ferry North Williamsburg landing departures for river commute.

---

## 6. Questions & Critique Prompts for the Reviewing Agent

1. **Volume Slider Debounce vs Step Buttons**: Telnet can choke if a web slider sends 50 volume updates in 500ms. Should the UI use pure `+ / -` step buttons (1dB / 0.5dB) or a debounced slider with immediate local optimistic UI?
2. **Denon Audio Feedback**: Does the AVR-X1200W report volume dB in half-dB steps (e.g. `MV505` = 50.5) and is the current Telnet protocol preferred over the newer HEOS CLI protocol on port 1255?
3. **Security / Guest Isolation**: Should the Petlibro dispense button and Litter-Robot cycle button be behind a simple household PIN/toggle to prevent casual guests or accidental pocket clicks?

