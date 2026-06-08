"""
Fix FlareSolverr registration in Prowlarr with correct IP, then verify.
"""
import paramiko, os, time, requests, json
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]
PROWLARR_IP  = os.environ["PROWLARR_IP"]
PROWLARR_KEY = os.environ["PROWLARR_API_KEY"]
FLARE_VMID   = "114"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def pct(vmid, cmd, timeout=30):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}", timeout=timeout)
    return out.read().decode().strip(), err.read().decode().strip()

# ── Get correct IP ────────────────────────────────────────────────────────────
print("=== CT114 IP ===")
raw_ip, _ = pct(FLARE_VMID, "hostname -I")
FLARE_IP = raw_ip.strip().split()[0]
print(f"IP: {FLARE_IP}")

# ── Check Docker container status ─────────────────────────────────────────────
print("\n=== FlareSolverr Docker status ===")
status, _ = pct(FLARE_VMID, "docker ps --filter name=flaresolverr --format '{{.Status}}'")
print(f"Container: {status or 'not found'}")

if "Up" not in status:
    print("Starting container...")
    pct(FLARE_VMID, "docker start flaresolverr 2>/dev/null || docker run -d --name flaresolverr --restart unless-stopped -p 8191:8191 -e LOG_LEVEL=info -e TZ=America/Detroit ghcr.io/flaresolverr/flaresolverr:latest", timeout=60)
    time.sleep(10)

# ── Verify HTTP ───────────────────────────────────────────────────────────────
print(f"\n=== Verifying FlareSolverr at {FLARE_IP}:8191 ===")
flare_ok = False
for attempt in range(8):
    try:
        r = requests.get(f"http://{FLARE_IP}:8191/", timeout=5)
        print(f"  HTTP {r.status_code} ✅  — {r.text[:80]}")
        flare_ok = True
        break
    except Exception as e:
        print(f"  Attempt {attempt+1}: {e}")
        time.sleep(5)

if not flare_ok:
    print("FlareSolverr not reachable — check logs:")
    logs, _ = pct(FLARE_VMID, "docker logs flaresolverr --tail 20 2>&1")
    print(logs)
    c.close()
    exit(1)

# ── Fix Prowlarr proxy registration ──────────────────────────────────────────
print(f"\n=== Fixing Prowlarr FlareSolverr proxy ===")
r_proxies = requests.get(
    f"http://{PROWLARR_IP}:9696/api/v1/indexerProxy",
    headers={"X-Api-Key": PROWLARR_KEY}, timeout=10)
proxies = r_proxies.json()
print(f"Existing proxies: {[p.get('name') for p in proxies]}")

correct_url = f"http://{FLARE_IP}:8191"

# Delete any bad entries (wrong IP in URL)
for p in proxies:
    fields = {f["name"]: f.get("value","") for f in p.get("fields",[])}
    host_val = fields.get("host", "")
    if "flaresolverr" in p.get("name","").lower() and host_val != correct_url:
        print(f"  Deleting stale proxy id={p['id']} (host={host_val})")
        requests.delete(
            f"http://{PROWLARR_IP}:9696/api/v1/indexerProxy/{p['id']}",
            headers={"X-Api-Key": PROWLARR_KEY}, timeout=10)

# Re-fetch
r_proxies2 = requests.get(
    f"http://{PROWLARR_IP}:9696/api/v1/indexerProxy",
    headers={"X-Api-Key": PROWLARR_KEY}, timeout=10)
proxies2 = r_proxies2.json()
already_correct = any(
    any(f.get("value") == correct_url for f in p.get("fields",[]))
    for p in proxies2
)

if already_correct:
    print(f"  Proxy already correct: {correct_url} ✅")
else:
    payload = {
        "name": "FlareSolverr",
        "implementation": "FlareSolverr",
        "configContract": "FlareSolverrSettings",
        "tags": [],
        "fields": [
            {"name": "host", "value": correct_url},
            {"name": "requestTimeout", "value": 60}
        ]
    }
    r_add = requests.post(
        f"http://{PROWLARR_IP}:9696/api/v1/indexerProxy",
        headers={"X-Api-Key": PROWLARR_KEY, "Content-Type": "application/json"},
        data=json.dumps(payload), timeout=10)
    if r_add.status_code in (200, 201):
        print(f"  Registered FlareSolverr proxy ✅  host={correct_url}")
    else:
        print(f"  Failed: {r_add.status_code} {r_add.text[:300]}")

# ── Final proxy list ──────────────────────────────────────────────────────────
r_final = requests.get(
    f"http://{PROWLARR_IP}:9696/api/v1/indexerProxy",
    headers={"X-Api-Key": PROWLARR_KEY}, timeout=10)
for p in r_final.json():
    fields = {f["name"]: f.get("value","") for f in p.get("fields",[])}
    print(f"\n  Proxy: {p['name']}  host={fields.get('host')}  timeout={fields.get('requestTimeout')}")

c.close()
print(f"\nDone. FlareSolverr at http://{FLARE_IP}:8191")
