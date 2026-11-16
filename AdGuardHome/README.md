# Home Network Monitor (Windows 11 MVP)

A local-first dashboard that reads AdGuard Home DNS query logs, maps IP addresses to friendly device names, stores events in SQLite, and displays activity reports.

## What it can and cannot see

- Can record DNS domain lookups, client IPs, query types, and AdGuard filtering outcomes.
- Cannot show full URLs, page contents, searches, messages, video titles, or reliable app screen time.
- Mobile data, VPNs, encrypted DNS, and iCloud Private Relay may bypass or reduce visibility.
- A DNS lookup is not proof that a person viewed a page; apps routinely make background requests.

Use this transparently with your teenagers. Keep access to the dashboard restricted to the home LAN and set a sensible retention period.

## 1. Install AdGuard Home

1. Download the official Windows release from https://github.com/AdguardTeam/AdGuardHome/releases
2. Extract to `C:\AdGuardHome`.
3. Open PowerShell **as Administrator**:
   ```powershell
   cd C:\AdGuardHome
   .\AdGuardHome.exe
   ```
4. Complete the first-run wizard. Bind DNS to the PC's LAN interface (not just 127.0.0.1); set DNS port 53 and create a strong admin password.
5. Open `http://127.0.0.1:3000` to finish setup.
6. Register it as a Windows service from elevated PowerShell:
   ```powershell
   cd C:\AdGuardHome
   .\AdGuardHome.exe -s install
   .\AdGuardHome.exe -s start
   ```
7. In AdGuard Home, confirm DNS query logging is enabled. Add reputable family-safe blocklists / parental-control filtering in Filters. Start in monitoring mode and tune false positives before enforcing strict blocks.

Official setup instructions: https://adguard-dns.io/kb/adguard-home/getting-started/

## 2. Give the PC a stable LAN address

Preferred: create a DHCP reservation in the TPG modem for the Windows PC's network adapter MAC address. Find it with:
```powershell
ipconfig /all
```
Reserve an address outside the router's dynamic pool if the router requires that. Example only: `192.168.1.10`. Do not copy this example until you have checked your actual subnet and DHCP range.

If the TPG firmware does not offer DHCP reservations, configure a static IPv4 address on Windows only after checking the subnet, gateway, and DHCP pool. Avoid address conflicts.

## 3. Configure TPG router DNS

1. Browse to the default gateway shown by `ipconfig` (TPG Wi-Fi Max instructions commonly use `https://192.168.1.1`; your gateway may differ).
2. Sign in and look for LAN / DHCP / DNS settings.
3. Set the DNS server advertised to LAN clients to the reserved PC address (example `192.168.1.10`).
4. Do not enter a public secondary DNS server: clients may use it and bypass filtering.
5. Save, then reconnect one test iPhone/iPad to Wi-Fi and verify its DNS requests appear in AdGuard Home with a distinct client IP.

If the TPG router cannot advertise custom DNS:
- First check whether it supports a separate DHCP DNS option in advanced settings or a firmware update.
- Do not enable a second DHCP server on Windows. AdGuard Home's DHCP server is not supported on Windows.
- As a fallback, set DNS manually on each iPhone/iPad Wi-Fi network (Settings > Wi-Fi > tap ⓘ > Configure DNS > Manual > add the PC's reserved IP). This only applies to that Wi-Fi network and does not cover mobile data.

## 4. Install the Python platform

Install Python 3.11 or newer. In PowerShell:
```powershell
mkdir C:\HomeNetMonitor
cd C:\HomeNetMonitor
# Copy the project files into this directory.
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` with your AdGuard Home URL, username and password. Keep the password private. Do not commit `.env` to Git.

Edit `devices.json` with actual DHCP-reserved device IPs and friendly names. Example IPs are placeholders.

## 5. Start the services

PowerShell window 1:
```powershell
cd C:\HomeNetMonitor
.\.venv\Scripts\Activate.ps1
uvicorn monitor:app --host 0.0.0.0 --port 8000
```

PowerShell window 2:
```powershell
cd C:\HomeNetMonitor
.\.venv\Scripts\Activate.ps1
streamlit run dashboard.py --server.address 0.0.0.0 --server.port 8501
```

Open on the PC:
- Dashboard: http://127.0.0.1:8501
- API health: http://127.0.0.1:8000/health
- API docs: http://127.0.0.1:8000/docs

To access from another trusted home device, use `http://<PC-LAN-IP>:8501`. Do not port-forward either service to the internet.

## 6. Windows Firewall

Run elevated PowerShell. Replace `192.168.1.0/24` with your actual LAN subnet:
```powershell
New-NetFirewallRule -DisplayName "HomeNet DNS UDP" -Direction Inbound -Protocol UDP -LocalPort 53 -Action Allow -RemoteAddress LocalSubnet
New-NetFirewallRule -DisplayName "HomeNet DNS TCP" -Direction Inbound -Protocol TCP -LocalPort 53 -Action Allow -RemoteAddress LocalSubnet
New-NetFirewallRule -DisplayName "HomeNet Dashboard" -Direction Inbound -Protocol TCP -LocalPort 8501 -Action Allow -RemoteAddress LocalSubnet
New-NetFirewallRule -DisplayName "HomeNet API" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -RemoteAddress LocalSubnet
```
AdGuard's setup wizard may add its own firewall rules. Avoid exposing admin ports to the public internet.

## 7. Device identification and iOS settings

For each child's device:
1. Connect it to the home Wi-Fi.
2. Record its current Wi-Fi IP from the router's connected-device list or device Wi-Fi details.
3. Add that IP to `devices.json`.
4. If the iPhone/iPad uses a private Wi-Fi address, keep its per-network address mode consistent (Fixed, where available) so the router's reservation remains stable. Do not disable privacy protections globally.
5. Reconnect and verify the IP and name in the dashboard.

## 8. Reports and retention

- Dashboard: http://127.0.0.1:8501
- CSV export: dashboard download button or `http://127.0.0.1:8000/api/report.csv?days=7`
- API: `/api/devices`, `/api/events`, `/health`
- Delete records older than 30 days: `DELETE http://127.0.0.1:8000/api/old-events?days=30`

The MVP stores DNS events in SQLite. Review retention regularly; do not collect more history than you need.

## 9. Troubleshooting

- No DNS logs: verify AdGuard listens on the LAN interface, Windows firewall allows TCP/UDP 53, router DHCP advertises the PC IP, and test devices renewed their DHCP leases.
- All devices show as router IP: router DNS proxy may be forwarding requests. Check whether the router can hand out the AdGuard IP directly. Otherwise use per-device DNS as a fallback.
- Some domains are missing: apps may use encrypted DNS, VPNs, Private Relay, hard-coded DNS, or mobile data.
- Internet stops when PC is off: expected if all devices depend on this DNS server. Keep PC powered on, or restore router DNS to automatic/public DNS temporarily.
- False positives: use AdGuard query log to identify the matched rule and allowlist only the domain needed.

## 10. Next development steps

1. Add authenticated dashboard access and role separation.
2. Add a daily report job (CSV/email) and alert thresholds.
3. Add router integration if its local API is documented and supported.
4. Add explicit device onboarding and IP/MAC history.
5. Add DNS-over-HTTPS / VPN policy only with informed household agreement and a clear exception process.
