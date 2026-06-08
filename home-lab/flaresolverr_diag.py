"""
Diagnose FlareSolverr bypass failures for 1337x.
Tests:
1. FlareSolverr health check
2. Direct solve request against 1337x.to
3. Check if CT114 has network access / correct DNS
4. Check Prowlarr proxy config
"""
import paramiko, os, time, requests, json
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]
PROWLARR_IP  = os.environ["PROWLARR_IP"]
PROWLARR_KEY = os.environ["PROWLARR_API_KEY"]
FLARE_IP     = os.environ["FLARESOLVERR_IP"]
FLARE_VMID   = "114"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def pct(vmid, cmd, timeout=30):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}", timeout=timeout)
    return out.read().decode().strip(), err.read().decode().strip()

# ── 1. FlareSolverr health ────────────────────────────────────────────────────
print("=== 1. FlareSolverr health ===")
try:
    r = requests.get(f"http://{FLARE_IP}:8191/", timeout=5)
    data = r.json()
    print(f"  Status: {r.status_code}")
    print(f"  Version: {data.get('version')}")
    print(f"  User-Agent: {data.get('userAgent','')[:80]}")
except Exception as e:
    print(f"  ERROR: {e}")

# ── 2. Direct solve request ───────────────────────────────────────────────────
print("\n=== 2. FlareSolverr solve request for 1337x.to ===")
try:
    payload = {
        "cmd": "request.get",
        "url": "https://1337x.to",
        "maxTimeout": 60000
    }
    r2 = requests.post(f"http://{FLARE_IP}:8191/v1",
                       headers={"Content-Type": "application/json"},
                       data=json.dumps(payload), timeout=90)
    result = r2.json()
    print(f"  HTTP status: {r2.status_code}")
    print(f"  solution.status: {result.get('solution', {}).get('status')}")
    print(f"  solution.response (first 200): {str(result.get('solution', {}).get('response', ''))[:200]}")
    if result.get('message'):
        print(f"  message: {result['message']}")
except Exception as e:
    print(f"  ERROR: {e}")

# ── 3. Network from CT114 ─────────────────────────────────────────────────────
print("\n=== 3. CT114 network ===")
out_ip, _ = pct(FLARE_VMID, "curl -s --max-time 5 https://api.ipify.org 2>/dev/null || echo timeout")
print(f"  External IP: {out_ip}")

out_dns, _ = pct(FLARE_VMID, "cat /etc/resolv.conf")
print(f"  resolv.conf: {out_dns}")

out_res, _ = pct(FLARE_VMID, "getent hosts 1337x.to 2>&1 | head -3")
print(f"  DNS 1337x.to: {out_res}")

# ── 4. Docker container logs ──────────────────────────────────────────────────
print("\n=== 4. FlareSolverr container logs (last 30 lines) ===")
logs, _ = pct(FLARE_VMID, "docker logs flaresolverr --tail 30 2>&1")
print(logs)

# ── 5. Prowlarr proxy config ──────────────────────────────────────────────────
print("\n=== 5. Prowlarr proxy config ===")
r3 = requests.get(f"http://{PROWLARR_IP}:9696/api/v1/indexerProxy",
                  headers={"X-Api-Key": PROWLARR_KEY}, timeout=10)
for p in r3.json():
    fields = {f["name"]: f.get("value") for f in p.get("fields", [])}
    print(f"  name={p['name']}  host={fields.get('host')}  timeout={fields.get('requestTimeout')}")

c.close()
