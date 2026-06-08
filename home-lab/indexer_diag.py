"""Diagnose why indexers are offline - check backoff, logs, VPN, and what errors are occurring."""
import urllib.request, json, urllib.error, paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR = f"http://{_env_prowlarr_ip}:9696"
KEY = os.environ["PROWLARR_API_KEY"]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def lxc(vmid, cmd, timeout=20):
    _, out, _ = ssh.exec_command(f"pct exec {vmid} -- {cmd}", timeout=timeout)
    return out.read().decode(errors="replace").strip()

def get(path, timeout=15):
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, headers={"X-Api-Key": KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

# 1. Current VPN status
print("=== VPN Status ===")
vpn = lxc("110", "systemctl is-active openvpn@client")
tun = lxc("110", "ip addr show tun0 2>/dev/null | grep 'inet '")
pub = lxc("110", "curl -s --max-time 6 https://api.ipify.org 2>/dev/null")
print(f"  openvpn@client: {vpn}")
print(f"  tun0: {tun}")
print(f"  Public IP: {pub}")

# 2. All indexer statuses (backoff)
print()
print("=== Indexer backoff status ===")
try:
    statuses = get("indexerstatus")
    indexers = get("indexer")
    idx_map = {i["id"]: i["name"] for i in indexers}
    if not statuses:
        print("  No backoff entries")
    for s in statuses:
        name = idx_map.get(s.get("indexerId"), f"id={s.get('indexerId')}")
        until = s.get("disabledTill", "?")[:19]
        count = s.get("mostRecentFailure", "?")
        print(f"  {name}: disabled until {until}  failures={s.get('failedCount','?')}")
except Exception as e:
    print(f"  Error: {e}")

# 3. Last 60 lines of Prowlarr log - all warn/error entries
print()
print("=== Recent Prowlarr errors/warnings (last 80 lines of log) ===")
log = lxc("110",
    "grep -E '\\|Warn\\||\\|Error\\|' /var/lib/prowlarr/logs/prowlarr.txt 2>/dev/null | tail -60",
    timeout=15)
print(log or "  (no warn/error entries)")

# 4. VPN routing
print()
print("=== CT110 routing table ===")
print(lxc("110", "ip route show"))

# 5. DNS
print()
print("=== CT110 DNS ===")
print(lxc("110", "cat /etc/resolv.conf"))

# 6. Test direct reachability of each indexer site from CT110
print()
print("=== Site reachability from CT110 (VPN) ===")
sites = [
    ("1337x.to", "https://1337x.to/"),
    ("eztvx.to", "https://eztvx.to/"),
    ("kickass", "https://kickass.torrentbay.st/"),
    ("nyaa.si", "https://nyaa.si/"),
    ("rutracker.org", "https://rutracker.org/"),
    ("torrentgalaxy", "https://torrentgalaxy.to/"),
    ("limetorrents", "https://www.limetorrents.lol/"),
]
for name, url in sites:
    r = lxc("110",
        f"curl -sL --max-time 8 -o /dev/null -w '%{{http_code}} %{{url_effective}}' '{url}' 2>/dev/null",
        timeout=15)
    print(f"  {name}: {r or '(no response)'}")

# 7. FlareSolverr health
print()
print("=== FlareSolverr health ===")
flare_h = lxc("110", f"curl -s --max-time 5 http://{os.environ['FLARESOLVERR_IP']}:8191/health 2>/dev/null")
print(f"  CT114 ({os.environ['FLARESOLVERR_IP']}:8191): {flare_h}")

ssh.close()
