"""
Add YTS directly to Radarr (bypassing Prowlarr VPN) since CT110's PIA IP is blocked by YTS.
CT107 (Radarr) has no VPN so it can reach YTS directly.
"""
import paramiko, os, time, urllib.request, json, urllib.error
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]

_env_radarr_ip = os.environ["RADARR_IP"]
RADARR = f"http://{_env_radarr_ip}:7878"
RADARR_KEY = os.environ["RADARR_API_KEY"]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def run_host(cmd, timeout=30):
    chan = ssh.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)
    stdout = chan.makefile("rb").read().decode(errors="replace").strip()
    stderr = chan.makefile_stderr("rb").read().decode(errors="replace").strip()
    chan.close()
    return stdout or stderr

def radarr_get(path):
    req = urllib.request.Request(RADARR + "/api/v3/" + path, headers={"X-Api-Key": RADARR_KEY})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def radarr_post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(RADARR + "/api/v3/" + path, data=body,
                                  headers={"X-Api-Key": RADARR_KEY, "Content-Type": "application/json"})
    req.get_method = lambda: "POST"
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"{e.code}: {e.read().decode()[:300]}"

# Step 1: Verify CT107 (Radarr) can reach YTS directly
print("=== Step 1: CT107 connectivity to YTS mirrors ===")
test_script = """#!/bin/sh
for host in yts.mx yts.bz movies-api.accel.li; do
    url="https://${host}/api/v2/list_movies.json?limit=1"
    code=$(curl -sL --max-time 12 -o /tmp/y.json -w "%{http_code}" "$url" 2>/dev/null)
    if [ "$code" = "200" ]; then
        status=$(python3 -c "import json; d=json.load(open('/tmp/y.json')); print(d.get('status','?'))" 2>/dev/null)
        echo "OK $host status=$status"
    else
        echo "FAIL $host code=$code"
    fi
done
"""
with ssh.open_sftp() as sftp:
    with sftp.file("/tmp/yts_ct107.sh", "w") as f:
        f.write(test_script)

result = run_host("chmod +x /tmp/yts_ct107.sh && pct push 107 /tmp/yts_ct107.sh /tmp/yts_ct107.sh && pct exec 107 -- sh /tmp/yts_ct107.sh", timeout=60)
print(result)

# Determine working host
working_host = None
for line in result.splitlines():
    if line.startswith("OK "):
        working_host = line.split()[1]
        print(f"\n  --> Using: {working_host}")
        break

if not working_host:
    print("\nNo YTS host reachable from CT107 either. Exiting.")
    ssh.close()
    exit(1)

# Step 2: Check if Radarr already has a direct YTS indexer
print()
print("=== Step 2: Current Radarr indexers ===")
idxs = radarr_get("indexer")
for i in idxs:
    print(f"  id={i['id']} {i['name']}")

existing_yts = next((i for i in idxs if "yts" in i["name"].lower() and "prowlarr" not in i["name"].lower()), None)
if existing_yts:
    print(f"\nDirect YTS already exists (id={existing_yts['id']}), will update URL.")

# Step 3: Get Radarr's indexer schema for Torznab/YTS
print()
print("=== Step 3: Adding YTS as direct Torznab indexer in Radarr ===")

# Radarr supports Torznab natively. We add Prowlarr's YTS proxy but using
# the /8/ path which routes through Prowlarr. BUT since CT110 VPN blocks YTS,
# we need a direct native indexer instead.
# Radarr doesn't have a native YTS Cardigann - we use Jackett-style Torznab
# pointing at Prowlarr's /8/ endpoint which itself calls YTS.
# 
# Since that's blocked, alternative: disable YTS in Prowlarr, add a direct
# HTTP-based indexer... but Radarr only supports Torznab/Newznab natively.
#
# Best approach: Keep YTS in Prowlarr but change Prowlarr's VPN routing
# so YTS traffic bypasses the VPN (uses eth0 directly).

print("  Radarr only supports Torznab/Newznab natively - can't add YTS API directly.")
print("  Will configure Prowlarr to bypass VPN for YTS traffic instead.")

ssh.close()

# Step 4: Add a routing exception in CT110 so YTS IPs bypass tun0
print()
print("=== Step 4: Plan - Route YTS around VPN on CT110 ===")
print("""
  Approach: Add a route exception in CT110 so that YTS API hosts
  use eth0 (direct internet) instead of tun0 (PIA VPN).
  
  The VPN pushes 0.0.0.0/1 and 128.0.0.0/1 via tun0, covering all traffic.
  We add a more-specific host route for YTS IPs via eth0's gateway.
  
  This makes YTS reachable with a non-VPN IP while everything else stays VPN.
""")
print("Run yts_vpn_bypass.py to implement this fix.")
