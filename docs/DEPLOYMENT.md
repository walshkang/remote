# 🚀 Deployment Guide: Running 'Remote' 24/7 on a VM / Cloud

This guide covers deploying the Remote server so it runs 24/7 without needing your Mac turned on.

---

## 1. Network Connectivity Overview

Before picking a hosting provider, here is how each device communicates when the server runs in the cloud:

| Integration | Protocol | Reaching it from a Cloud VM |
|---|---|---|
| **Litter-Robot 4** | Whisker Cloud | ✅ **100% Native** (talks directly to Whisker AWS cloud) |
| **BuildingLink** | Email / Resident API | ✅ **100% Native** (fetches deliveries directly) |
| **Petlibro Granary** | Petlibro Cloud | ✅ **100% Native** (talks directly to Petlibro cloud) |
| **Philips Hue** | Local / Cloud | ✅ **Hue Cloud API** or **Local Bridge via Router** |
| **Denon AVR-X1200W**| Local LAN (`192.168.1.226`) | ⚡ **See 3 connection options below** |

### How the Cloud Server talks to your Denon AVR (`192.168.1.226`):

1. **Option A: Tailscale Subnet Router (Zero Port Forwarding — Most Popular)**:
   * Install free [Tailscale](https://tailscale.com) on an Apple TV, Raspberry Pi, home server, or router, and turn on `--advertise-routes=192.168.1.0/24`.
   * Install Tailscale on your VM.
   * Your VM can now talk directly to `192.168.1.226:23` (Denon) and `192.168.1.154` (Hue) securely as if it were plugged into your living room!
2. **Option B: Fios Router Port-Forward (Locked to your VM's Static IP)**:
   * On your Fios CR1000A router (`http://192.168.1.1`), add a port-forward rule for port `23` and `80` to `192.168.1.226`.
   * **Crucial Security**: Set **Source IP** to *only* your VM's public IP address. The router firewall drops every other connection attempt from the internet.
3. **Option C: Browser-to-LAN Relay**:
   * The web app is served from the VM (`https://remote.yourdomain.com`).
   * For the Denon, the client phone's browser fires local `fetch('http://192.168.1.226/goform/formiPhoneAppDirect.xml?...', { mode: 'no-cors' })` directly over Wi-Fi.

---

## 2. Deploying on Oracle Cloud (Always Free VM)

Oracle Cloud provides up to **4 Ampere ARM cores, 24GB RAM, and a static IPv4 address for $0/month forever**.

### Step 1: Create an Instance in Oracle Cloud
1. Sign up / log into [Oracle Cloud Console](https://cloud.oracle.com).
2. Go to **Compute** ➔ **Instances** ➔ **Create Instance**.
3. Choose **Ubuntu 24.04 LTS** (or 22.04).
4. Under **Shape**, select either:
   - **VM.Standard.A1.Flex** (Ampere ARM - Always Free, up to 4 OCPUs / 24GB RAM)
   - OR **VM.Standard.E2.1.Micro** (AMD x86 - Always Free).
5. Download your SSH private key (`ssh-key.key`), and click **Create**.
6. Note your instance's **Public IP address**.

### Step 2: Open Port 8000 (and 80/443) in Oracle Virtual Cloud Network (VCN)
1. On the instance page, click your **Subnet** link.
2. Click **Default Security List** ➔ **Add Ingress Rules**:
   - **Source CIDR**: `0.0.0.0/0` (or restricted to your home IP)
   - **IP Protocol**: TCP
   - **Destination Port Range**: `80, 443, 8000`
   - Click **Add Ingress Rules**.

### Step 3: Connect & Deploy with Docker
SSH into your instance:
```bash
ssh -i /path/to/ssh-key.key ubuntu@<YOUR_VM_PUBLIC_IP>
```

Install Docker and Git on the VM:
```bash
sudo apt update && sudo apt install -y git docker.io docker-compose-v2
sudo usermod -aG docker $USER
newgrp docker
```

Clone your repository and configure `.env`:
```bash
git clone https://github.com/walshkang/remote.git
cd remote

# Create your .env with your credentials
cp .env.example .env
nano .env   # Fill in LITTER_ROBOT_EMAIL, LITTER_ROBOT_PASSWORD, etc.
```

Start the server:
```bash
docker compose up -d
```

Check logs:
```bash
docker compose logs -f
```

---

## 3. Alternative: Deploying to Fly.io or Railway (No Server Management)

If you prefer not to manage Linux updates or SSH keys, container platforms build directly from your GitHub repo:

### Via Fly.io:
1. Install flyctl: `brew install flyctl`
2. Run `fly launch` inside the `remote` folder.
3. Set your secrets:
   ```bash
   fly secrets set LITTER_ROBOT_EMAIL=your@email.com LITTER_ROBOT_PASSWORD=secret
   ```
4. Deploy: `fly deploy`.

---

## 4. Hooking Up Your Domain (`remote.yourdomain.com`)

1. Go to your DNS provider (Cloudflare, Namecheap, Route 53, etc.).
2. Add an **A Record**:
   - **Name**: `remote`
   - **Target**: `<YOUR_VM_PUBLIC_IP>`
3. If using Cloudflare, enable the Proxy (orange cloud) for automatic SSL certificates and DDoS protection!
