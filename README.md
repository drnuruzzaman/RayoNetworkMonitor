# HomeNet Monitor

A home network dashboard for Windows. See every device on your Wi-Fi, which apps each one uses and
for how long, and pause the internet or block apps per device, on a schedule or with one tap.

Everything is configured from the web UI. No config files to edit.

## How it works

```
 iPhone · iPad · Android · MacBook · Windows
                    │  DNS lookups (youtube.com, tiktok.com…)
                    ▼
          ┌──────────────────────┐         ┌──────────────────────────┐
          │ AdGuard Home (DNS)   │◄───────►│ HomeNet Monitor          │
          │ logs & blocks        │   API   │ • scans the LAN (ARP)    │
          └──────────────────────┘         │ • turns DNS into usage   │
               this Windows PC             │ • pauses / schedules     │
                                           │ • web UI on :8090        │
                                           └──────────────────────────┘
```

| Feature | Needs AdGuard Home? |
|---|---|
| Device discovery, online/offline history, new-device alerts | No |
| App usage & screen-time estimates, website lists | Yes |
| Pause internet, block apps, bedtime schedules, safe search | Yes |

## Quick start

1. **Start HomeNet** (first run installs packages and builds the UI):
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\start.ps1
   ```
   Open <http://localhost:8090>. The setup wizard walks you through the rest.
2. **Install AdGuard Home** (Administrator PowerShell):
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\install-adguard.ps1
   ```
   Finish its wizard at <http://127.0.0.1:3000> (admin port **3000**, DNS on **all interfaces :53**),
   then enter its username and password in HomeNet → Settings → AdGuard Home.
3. **Point devices at this PC for DNS.** On the TPG modem: reserve this PC's IP and set it as the
   only DNS server under LAN/DHCP. If the modem doesn't allow that, set DNS on each device. Step-by-step
   instructions are in Settings → Setup guide.
4. **Optional:** start automatically at sign-in and allow phones to open the dashboard:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\install-autostart.ps1
   ```

### Modem won't let you change DNS? (e.g. TPG)

HomeNet has its own **Address server (DHCP)**. AdGuard Home's DHCP server doesn't run on Windows, so HomeNet
provides one. If your modem lets you switch *its* DHCP server off, HomeNet hands out addresses instead and
points every device's DNS at this PC. Open **Address server** in the sidebar and follow the steps. It needs a
static IP on this PC, plus this one-off firewall rule (Administrator PowerShell):
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\allow-dhcp-firewall.ps1
```
To undo, turn DHCP back on in the modem and turn the address server off.

## Good to know

- **Keep the PC on.** Devices using it for DNS lose internet if it sleeps. Set power to *never sleep*.
- **Private MAC addresses.** For each phone or tablet, set *Private Wi-Fi Address* to **Fixed** (iOS) or *Use device MAC* (Android) for your home network.
- **Estimates, not spyware.** HomeNet sees which services a device looks up, not page contents. Encrypted DNS in browsers and VPN apps can go around it.
- **Household.** Let the people on your network know it's monitored.
- **All data stays local** in `data\homenet.db`. AdGuard's password is encrypted with your Windows account (DPAPI).

## Project layout

```
backend/   FastAPI app, SQLite, scanner, AdGuard sync, schedules (Python 3.11+)
frontend/  React + Tailwind UI (Vite), built into frontend/dist and served by the backend
scripts/   AdGuard installer, autostart/firewall helper
start.ps1  one-click launcher
```

Dev mode: run `start.ps1`, then `npm run dev` in `frontend/` for hot reload on :5173 (proxied to the backend).
