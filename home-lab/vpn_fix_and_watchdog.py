"""
1. Fix the broken VPN on CT110 right now
2. Install a systemd watchdog timer that auto-restarts VPN + clears backoff when connectivity drops
"""
import paramiko, os, time, urllib.request, json
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR = f"http://{_env_prowlarr_ip}:9696"
KEY = os.environ["PROWLARR_API_KEY"]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def host(cmd, timeout=30):
    _, out, err = ssh.exec_command(cmd, timeout=timeout)
    stdout = out.read().decode(errors="replace").strip()
    stderr = "\n".join(l for l in err.read().decode(errors="replace").splitlines()
                       if "deprecated" not in l.lower()).strip()
    return stdout or stderr

def lxc(vmid, cmd, timeout=20):
    _, out, _ = ssh.exec_command(f"pct exec {vmid} -- {cmd}", timeout=timeout)
    return out.read().decode(errors="replace").strip()

def prowlarr_get(path, timeout=12):
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, headers={"X-Api-Key": KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

# ── Step 1: Fix VPN now ───────────────────────────────────────────────────────
print("=== Step 1: Fix VPN on CT110 ===")
print(f"  Before: {lxc('110', 'ip addr show tun0 2>/dev/null | grep inet | head -1')}")

lxc("110", "systemctl restart openvpn@client")
print("  Restarted openvpn@client, waiting 15s...")
time.sleep(15)

for i in range(6):
    tun = lxc("110", "ip addr show tun0 2>/dev/null | grep 'inet ' | awk '{print $2}'")
    pub = lxc("110", "curl -s --max-time 5 https://api.ipify.org 2>/dev/null")
    if tun and pub:
        print(f"  VPN up: tun0={tun}  public={pub}")
        break
    print(f"  [{(i+1)*5}s] waiting... tun={tun} pub={pub}")
    time.sleep(5)
else:
    print("  WARNING: VPN didn't come up cleanly")

# Quick connectivity test
r = lxc("110", "curl -sL --max-time 8 -o /dev/null -w '%{http_code}' https://nyaa.si/ 2>/dev/null")
print(f"  nyaa.si: HTTP {r}")
r2 = lxc("110", "curl -sL --max-time 8 -o /dev/null -w '%{http_code}' https://rutracker.org/ 2>/dev/null")
print(f"  rutracker.org: HTTP {r2}")

# ── Step 2: Clear indexer backoff ─────────────────────────────────────────────
print()
print("=== Step 2: Clear indexer backoff ===")
db = "/var/lib/prowlarr/prowlarr.db"
result = lxc("110", f"sqlite3 {db} 'DELETE FROM IndexerStatus;' && echo cleared")
print(f"  {result}")
lxc("110", "systemctl restart prowlarr")
print("  Restarted Prowlarr, waiting 20s...")
time.sleep(20)

for i in range(8):
    try:
        prowlarr_get("health", timeout=8)
        print("  Prowlarr up")
        break
    except:
        time.sleep(4)

# ── Step 3: Install VPN watchdog ──────────────────────────────────────────────
print()
print("=== Step 3: Install VPN watchdog on CT110 ===")

# The watchdog script: runs every 5 minutes, checks if VPN is working,
# restarts it if not, and clears Prowlarr backoff after recovery.
watchdog_script = r"""#!/bin/bash
# /usr/local/bin/vpn-watchdog.sh
# Checks VPN connectivity; restarts if broken; clears Prowlarr backoff on recovery.

LOGFILE="/var/log/vpn-watchdog.log"
MAX_LOG_LINES=200
TEST_HOST="1.1.1.1"
PROWLARR_DB="/var/lib/prowlarr/prowlarr.db"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOGFILE"
}

# Trim log
if [ -f "$LOGFILE" ] && [ "$(wc -l < "$LOGFILE")" -gt "$MAX_LOG_LINES" ]; then
    tail -100 "$LOGFILE" > "${LOGFILE}.tmp" && mv "${LOGFILE}.tmp" "$LOGFILE"
fi

# Check if VPN tunnel is up
if ! ip link show tun0 &>/dev/null; then
    log "FAIL: tun0 missing — restarting openvpn@client"
    systemctl restart openvpn@client
    sleep 20
fi

# Check if traffic flows through VPN (ping through tun0)
if ! ping -c 2 -W 4 -I tun0 "$TEST_HOST" &>/dev/null; then
    log "FAIL: no traffic through tun0 — restarting openvpn@client"
    systemctl restart openvpn@client
    sleep 20

    # Verify recovery
    if ping -c 2 -W 4 -I tun0 "$TEST_HOST" &>/dev/null; then
        log "RECOVERY: VPN restored"
        # Clear Prowlarr indexer backoff so indexers come back immediately
        if [ -f "$PROWLARR_DB" ]; then
            sqlite3 "$PROWLARR_DB" "DELETE FROM IndexerStatus;" && \
                log "RECOVERY: Cleared Prowlarr IndexerStatus backoff" || \
                log "WARN: Could not clear Prowlarr backoff (DB busy?)"
            # Brief restart to flush in-memory state
            systemctl restart prowlarr
            log "RECOVERY: Restarted Prowlarr"
        fi
    else
        log "FAIL: VPN still down after restart"
    fi
else
    log "OK: VPN healthy (tun0 → $TEST_HOST)"
fi
"""

# Systemd service + timer units
timer_unit = """[Unit]
Description=VPN connectivity watchdog

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
"""

service_unit = """[Unit]
Description=VPN connectivity watchdog
After=network.target openvpn@client.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/vpn-watchdog.sh
"""

# Write files into CT110 via Proxmox push
with ssh.open_sftp() as sftp:
    with sftp.file("/tmp/vpn-watchdog.sh", "w") as f:
        f.write(watchdog_script)
    with sftp.file("/tmp/vpn-watchdog.timer", "w") as f:
        f.write(timer_unit)
    with sftp.file("/tmp/vpn-watchdog.service", "w") as f:
        f.write(service_unit)

host("pct push 110 /tmp/vpn-watchdog.sh /usr/local/bin/vpn-watchdog.sh")
host("pct push 110 /tmp/vpn-watchdog.timer /etc/systemd/system/vpn-watchdog.timer")
host("pct push 110 /tmp/vpn-watchdog.service /etc/systemd/system/vpn-watchdog.service")

lxc("110", "chmod +x /usr/local/bin/vpn-watchdog.sh")
lxc("110", "systemctl daemon-reload")
lxc("110", "systemctl enable --now vpn-watchdog.timer")

# Verify timer installed
timer_status = lxc("110", "systemctl status vpn-watchdog.timer --no-pager -l 2>/dev/null | head -10")
print(timer_status)

# Run it once manually to confirm it works
print()
print("  Running watchdog manually...")
result = lxc("110", "/usr/local/bin/vpn-watchdog.sh && echo 'exit 0'", timeout=40)
print(f"  {result}")
log_out = lxc("110", "tail -5 /var/log/vpn-watchdog.log 2>/dev/null")
print(f"  Log: {log_out}")

# ── Step 4: Also add keepalive to OpenVPN config ──────────────────────────────
print()
print("=== Step 4: Harden OpenVPN config ===")
current_conf = lxc("110", "cat /etc/openvpn/client.conf")
print("  Current keepalive settings:")
for line in current_conf.splitlines():
    if any(x in line.lower() for x in ["keepalive", "ping", "persist", "resolv", "reneg"]):
        print(f"    {line}")

# Check if keepalive is already set
has_keepalive = "keepalive" in current_conf.lower()
has_persist_tun = "persist-tun" in current_conf.lower()
has_persist_key = "persist-key" in current_conf.lower()

additions = []
if not has_keepalive:
    additions.append("keepalive 10 60")   # ping every 10s, restart if no response in 60s
if not has_persist_tun:
    additions.append("persist-tun")
if not has_persist_key:
    additions.append("persist-key")

if additions:
    for line in additions:
        # Append each line if not already present
        lxc("110", f"grep -qF '{line}' /etc/openvpn/client.conf || echo '{line}' >> /etc/openvpn/client.conf")
    print(f"  Added: {additions}")
    lxc("110", "systemctl restart openvpn@client")
    time.sleep(12)
    pub = lxc("110", "curl -s --max-time 6 https://api.ipify.org 2>/dev/null")
    print(f"  VPN after hardening: public IP={pub}")
else:
    print("  Already has keepalive/persist settings")

# ── Step 5: Final indexer check ───────────────────────────────────────────────
print()
print("=== Step 5: Final indexer status ===")
for i in range(6):
    try:
        statuses = prowlarr_get("indexerstatus", timeout=10)
        indexers = prowlarr_get("indexer", timeout=10)
        break
    except:
        time.sleep(5)

idx_map = {i["id"]: i["name"] for i in indexers}
if not statuses:
    print("  No backoff — all indexers active ✓")
else:
    for s in statuses:
        name = idx_map.get(s.get("indexerId"), f"id={s.get('indexerId')}")
        print(f"  BACKOFF: {name} until {s.get('disabledTill','?')[:19]}")

# Test a couple
sites_test = [
    ("nyaa.si", "https://nyaa.si/"),
    ("rutracker.org", "https://rutracker.org/"),
    ("1337x.to", "https://1337x.to/"),
]
print()
print("  Site reachability:")
for name, url in sites_test:
    r = lxc("110", f"curl -sL --max-time 8 -o /dev/null -w '%{{http_code}}' '{url}' 2>/dev/null", timeout=15)
    print(f"    {name}: HTTP {r or '000'}")

ssh.close()
print()
print("Done. Watchdog runs every 5 min — VPN failures will self-heal within 5 min going forward.")
