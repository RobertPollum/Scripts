"""
1. Clear remaining backoff (KAT, TorrentGalaxy)
2. Check rutracker reachability + try alternate PIA region if blocked
3. Verify all indexers working end-to-end
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

def lxc(vmid, cmd, timeout=20):
    _, out, _ = ssh.exec_command(f"pct exec {vmid} -- {cmd}", timeout=timeout)
    return out.read().decode(errors="replace").strip()

def prowlarr_get(path, timeout=12):
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, headers={"X-Api-Key": KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

db = "/var/lib/prowlarr/prowlarr.db"

# ── Step 1: Clear all remaining backoff ──────────────────────────────────────
print("=== Step 1: Clear all backoff ===")
r = lxc("110", f"sqlite3 {db} 'DELETE FROM IndexerStatus;' && echo cleared")
print(f"  {r}")
lxc("110", "systemctl restart prowlarr")
print("  Waiting 20s for Prowlarr...")
time.sleep(20)
for _ in range(8):
    try:
        prowlarr_get("health", timeout=8)
        print("  Prowlarr up")
        break
    except:
        time.sleep(4)

# ── Step 2: Rutracker — check which IPs work ─────────────────────────────────
print()
print("=== Step 2: Rutracker reachability ===")
pub_ip = lxc("110", "curl -s --max-time 5 https://api.ipify.org 2>/dev/null")
print(f"  Current PIA exit IP: {pub_ip}")
rut = lxc("110", "curl -sL --max-time 10 -o /dev/null -w '%{http_code}' https://rutracker.org/ 2>/dev/null", timeout=15)
print(f"  rutracker.org: HTTP {rut}")

if rut not in ("200", "301", "302"):
    print("  Blocked — trying alternate PIA regions...")
    # Try a few European regions
    regions = [
        "nl.privacy.network",
        "swiss.privacy.network",
        "germany.privacy.network",
        "france.privacy.network",
        "sweden.privacy.network",   # different Sweden node
    ]
    found = None
    for region in regions:
        print(f"  Switching to {region}...", end=" ", flush=True)
        lxc("110", f"sed -i 's|^remote .*|remote {region} 1198|' /etc/openvpn/client.conf")
        lxc("110", "systemctl restart openvpn@client")
        time.sleep(15)

        tun = lxc("110", "ip addr show tun0 2>/dev/null | grep 'inet ' | awk '{print $2}'")
        new_pub = lxc("110", "curl -s --max-time 6 https://api.ipify.org 2>/dev/null")
        if not tun or not new_pub:
            print(f"VPN didn't connect, skipping")
            continue

        rut_code = lxc("110", "curl -sL --max-time 10 -o /dev/null -w '%{http_code}' https://rutracker.org/ 2>/dev/null", timeout=15)
        print(f"IP={new_pub} rutracker={rut_code}")

        if rut_code in ("200", "301", "302"):
            print(f"  ✓ {region} works for rutracker (exit IP {new_pub})")
            found = region
            break

    if not found:
        print("  All regions blocked for rutracker — leaving on current region")
        # Revert to sweden (which works for other indexers)
        lxc("110", "sed -i 's|^remote .*|remote sweden.privacy.network 1198|' /etc/openvpn/client.conf")
        lxc("110", "systemctl restart openvpn@client")
        time.sleep(12)
        pub_ip = lxc("110", "curl -s --max-time 6 https://api.ipify.org 2>/dev/null")
        print(f"  Reverted to sweden, exit IP: {pub_ip}")
else:
    print("  rutracker.org reachable ✓")

# ── Step 3: Test all enabled indexers via Torznab ────────────────────────────
print()
print("=== Step 3: Torznab caps test for all enabled indexers ===")
# Wait a moment for backoff clear to take effect
time.sleep(5)
indexers = prowlarr_get("indexer")
enabled = [i for i in indexers if i.get("enable")]
print(f"  {len(enabled)} enabled indexers")

results = {}
for idx in sorted(enabled, key=lambda x: x["name"]):
    url = f"{PROWLARR}/{idx['id']}/api?t=caps&apikey={KEY}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
            results[idx["name"]] = f"OK ({len(data)}b)"
            print(f"  ✓ {idx['name']}")
    except urllib.request.HTTPError as e:
        results[idx["name"]] = f"HTTP {e.code}"
        print(f"  ✗ {idx['name']}: HTTP {e.code}")
    except Exception as e:
        results[idx["name"]] = str(e)[:60]
        print(f"  ✗ {idx['name']}: {str(e)[:60]}")
    time.sleep(2)

# ── Step 4: Summary ───────────────────────────────────────────────────────────
print()
print("=== Summary ===")
ok = [n for n, r in results.items() if r.startswith("OK")]
fail = [(n, r) for n, r in results.items() if not r.startswith("OK")]
print(f"  Working: {len(ok)}/{len(results)}")
if fail:
    print("  Failing:")
    for n, r in fail:
        print(f"    ✗ {n}: {r}")

# Final VPN state
print()
print("=== Final VPN state ===")
conf_remote = lxc("110", "grep '^remote ' /etc/openvpn/client.conf")
final_pub = lxc("110", "curl -s --max-time 6 https://api.ipify.org 2>/dev/null")
print(f"  Config: {conf_remote}")
print(f"  Exit IP: {final_pub}")

ssh.close()
