"""Quick CF indexer status check - VPN, backoff, FlareSolverr, recent logs."""
import urllib.request, json, paramiko, os
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

def get(path, timeout=12):
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, headers={"X-Api-Key": KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

# VPN
print("=== VPN ===")
vpn = lxc("110", "systemctl is-active openvpn@client")
tun = lxc("110", "ip addr show tun0 2>/dev/null | grep 'inet ' | awk '{print $2}'")
pub = lxc("110", "curl -s --max-time 6 https://api.ipify.org 2>/dev/null")
ping_ok = lxc("110", "ping -c 2 -W 4 -I tun0 1.1.1.1 2>/dev/null | grep -c 'bytes from' || echo 0")
print(f"  openvpn: {vpn}  tun0: {tun}  public: {pub}  ping_through_tun: {ping_ok}")

# Watchdog last run
print()
print("=== Watchdog last log ===")
print(lxc("110", "tail -5 /var/log/vpn-watchdog.log 2>/dev/null"))

# Backoff
print()
print("=== Indexer backoff ===")
try:
    statuses = get("indexerstatus")
    indexers = get("indexer")
    idx_map = {i["id"]: i["name"] for i in indexers}
    if not statuses:
        print("  None")
    for s in statuses:
        name = idx_map.get(s.get("indexerId"), f"id={s.get('indexerId')}")
        print(f"  {name}: until {s.get('disabledTill','?')[:19]}  failures={s.get('failedCount','?')}")
except Exception as e:
    print(f"  Error: {e}")

# FlareSolverr health
print()
print("=== FlareSolverr ===")
flare_h = lxc("110", f"curl -s --max-time 5 http://{os.environ['FLARESOLVERR_IP']}:8191/health 2>/dev/null")
print(f"  CT114 health: {flare_h}")

# Quick reachability of CF sites
print()
print("=== CF site reachability from CT110 ===")
for name, url in [("1337x.to", "https://1337x.to/"), ("eztvx.to", "https://eztvx.to/"), ("kickass", "https://kickass.torrentbay.st/")]:
    r = lxc("110", f"curl -sL --max-time 8 -o /dev/null -w '%{{http_code}}' '{url}' 2>/dev/null", timeout=15)
    print(f"  {name}: HTTP {r or '000'}")

# Recent CF-related errors
print()
print("=== Recent Prowlarr errors (CF/flare/1337x/eztv/kickass) ===")
log = lxc("110",
    "grep -iE 'flare|cloudflare|1337x|eztv|kickass|torrentgalaxy|blocked|challenge|unavailable' "
    "/var/lib/prowlarr/logs/prowlarr.txt 2>/dev/null | tail -20", timeout=15)
print(log or "  (none)")

ssh.close()
