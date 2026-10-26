# 🚀 Deployment Guide: Oracle Cloud VM + Porkbun (`remote.walshkang.com`)

This guide walks you through setting up an **Always Free Oracle Cloud VM**, configuring DNS at **Porkbun**, and deploying **Remote** with automatic HTTPS via **Caddy**.

---

## Architecture & How Devices Connect

```
           [ Phone on Wi-Fi / 5G ]
                      │
                      ▼ HTTPS (Port 443)
            [ remote.walshkang.com ]
                      │
                      ▼
           ┌──────────────────────────────────────────────┐
           │          Oracle Cloud Always Free VM         │
           │                                              │
           │   ┌──────────────┐      ┌────────────────┐   │
           │   │    Caddy     │─────▶│  Remote Server │   │
           │   │  (Auto-SSL)  │:8000 │ (Python/FastAPI)   │
           │   └──────────────┘      └────────────────┘   │
           └──────────────┬──────────────────┬────────────┘
                          │                  │
                          ▼ Cloud APIs       ▼ Home LAN (Tailscale / Port-forward)
                 [Litter-Robot / Whisker] [Denon AVR & Hue Bridge]
                 [BuildingLink Deliveries]
```

* **Cloud-Native Modules (Litter-Robot, BuildingLink, Petlibro)**: Work immediately out of the box from Oracle Cloud with zero router configuration.
* **LAN Modules (Denon AVR, Philips Hue)**: Can be reached from Oracle Cloud via a free Tailscale subnet router on your home network, or via router port-forwarding locked to your VM IP (see [Section 6](#6-connecting-local-lan-devices-denon--hue)).

---

## 1. Create your Free VM in Oracle Cloud

Oracle Cloud offers an **Always Free** tier that never expires.

1. Log in to your [Oracle Cloud Console](https://cloud.oracle.com).
2. Open the navigation menu (top-left) ➔ **Compute** ➔ **Instances**.
3. Click **Create Instance**.
4. Configure the instance:
   * **Name**: `remote-server` (or any name)
   * **Compartment**: Keep default (root)
   * **Image**: Click *Change Image* ➔ Select **Ubuntu 24.04** (or **Ubuntu 22.04 Minimal**).
   * **Shape**:
     * Recommended: **Ampere ARM** (`VM.Standard.A1.Flex`, 1–4 OCPUs, 6–24 GB RAM — Always Free).
     * Alternative: **AMD x86** (`VM.Standard.E2.1.Micro`, 1 OCPU, 1 GB RAM — Always Free).
   * **Networking**: Keep "Create new virtual cloud network" and ensure **"Assign a public IPv4 address"** is checked (**Yes**).
   * **Add SSH Keys**:
     * Select **Generate a key pair for me** and click **Save Private Key** (download it as `ssh-key.key` to your Mac, e.g. `~/.ssh/oracle_remote.key`).
     * *Alternatively, select "Paste public keys" if you have an existing `~/.ssh/id_rsa.pub` or `~/.ssh/id_ed25519.pub`.*
5. Click **Create**.
6. Wait 1–2 minutes until the status turns **Running**. Copy down your **Public IP Address** (e.g. `129.153.x.x`).

---

## 2. Configure the 2 Firewalls (Oracle Console & OS iptables)

> [!IMPORTANT]
> Oracle Cloud has **two** firewalls: the Oracle VCN Security List **and** the Ubuntu OS internal firewall (`iptables`). Both must allow ports 80 and 443!

### A. Oracle Cloud VCN Security List (Cloud Firewall)
1. On your instance page, under **Instance Details**, scroll down to **Primary VNIC** and click on your **Subnet** link.
2. Click on the **Default Security List for...**.
3. Under **Ingress Rules**, click **Add Ingress Rules**:
   * **Source Type**: CIDR
   * **Source CIDR**: `0.0.0.0/0`
   * **IP Protocol**: TCP
   * **Destination Port Range**: `80,443`
   * **Description**: `HTTP and HTTPS for Caddy SSL`
4. Click **Add Ingress Rules**.

---

## 3. Configure Porkbun DNS (`remote.walshkang.com`)

1. Log into your [Porkbun Account](https://porkbun.com).
2. Go to **Domain Management** ➔ Find `walshkang.com` ➔ Click **DNS**.
3. Add a new record:
   * **Type**: `A`
   * **Host**: `remote`
   * **Answer**: `<YOUR_ORACLE_VM_PUBLIC_IP>` (e.g. `129.153.x.x`)
   * **TTL**: `600` (or default 300)
4. Click **Submit**.

> [!TIP]
> Porkbun updates records in seconds. You can verify it on your Mac:
> ```bash
> dig remote.walshkang.com +short
> ```
> It should return your Oracle VM's public IP.

---

## 4. Prepare the Oracle VM (Run in your Mac Terminal)

Set permissions on your downloaded SSH key on your Mac:
```bash
chmod 400 ~/.ssh/oracle_remote.key
```

SSH into your new VM:
```bash
ssh -i ~/.ssh/oracle_remote.key ubuntu@<YOUR_ORACLE_VM_PUBLIC_IP>
```

### Once logged into the Ubuntu VM, run:

#### 1. Open the Ubuntu OS Firewall (iptables)
Oracle's default Ubuntu images block ports 80 and 443 by default:
```bash
# Allow HTTP (80) and HTTPS (443) through Ubuntu iptables
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save || sudo apt install -y iptables-persistent && sudo netfilter-persistent save
```

#### 2. Install Docker & Docker Compose
```bash
sudo apt update && sudo apt install -y git docker.io docker-compose-v2
sudo usermod -aG docker $USER
newgrp docker
```

---

## 5. Clone and Launch Remote

On the VM:

```bash
# 1. Clone your repository
git clone https://github.com/walshkang/remote.git
cd remote

# 2. Configure .env
cp .env.example .env
nano .env
```

In `.env`, make sure to set:
```bash
DOMAIN=remote.walshkang.com

# Active modules (start with cloud modules, plus denon/hue when ready)
REMOTE_MODULES=litter_robot,buildinglink,demo

# Whisker / Litter-Robot 4 credentials
LITTER_ROBOT_EMAIL=your_whisker_email@example.com
LITTER_ROBOT_PASSWORD=your_whisker_password

# BuildingLink token (if you have one, or run the auth CLI)
BUILDINGLINK_ACCESS_TOKEN=
```
*(Press `Ctrl + O` then `Enter` to save, and `Ctrl + X` to exit nano).*

#### 3. Start the application
```bash
docker compose up -d --build
```

#### 4. Verify Caddy & Remote Logs
```bash
docker compose logs -f
```

You should see:
* `caddy` automatically requesting and receiving a free Let's Encrypt / ZeroSSL TLS certificate for `remote.walshkang.com`.
* `remote` starting Uvicorn on port 8000.

🎉 Open **`https://remote.walshkang.com`** in your browser (phone or desktop)! It will show a valid SSL lock icon and load your dashboard.

---

## 6. Connecting Local LAN Devices (Denon & Hue)

Because the Denon AVR (`192.168.1.226`) and Philips Hue Bridge (`192.168.1.154`) sit on your home Wi-Fi subnet, an outside cloud VM cannot reach private `192.168.1.x` addresses directly without a secure path.

### Option A: Free Tailscale Subnet Router (Recommended)
1. Install [Tailscale](https://tailscale.com) on any always-on machine at home (Mac, Raspberry Pi, Apple TV running tvOS 17+, or a home server).
2. Enable subnet routing on your home machine:
   ```bash
   sudo tailscale up --advertise-routes=192.168.1.0/24
   ```
3. Install Tailscale on your Oracle Cloud VM:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up --accept-routes
   ```
4. Now your Oracle Cloud VM can reach `192.168.1.226` and `192.168.1.154` as if it were plugged into your home router! Enable `denon` and `hue` in `.env`:
   ```bash
   REMOTE_MODULES=denon,hue,litter_robot,buildinglink,demo
   ```
   Restart with `docker compose restart remote`.

### Option B: Router Port-Forwarding (Source-IP Locked)
If you do not want Tailscale:
1. Log into your home router (`http://192.168.1.1`).
2. Add a port-forward rule for TCP Port `23` forwarding to `192.168.1.226`.
3. Set the **Source IP Filter** to *strictly* your Oracle VM's public IP (`129.153.x.x`). All other internet IPs are dropped by the router firewall.
4. Point `DENON_HOST=<YOUR_HOME_PUBLIC_IP>` in `.env`.
