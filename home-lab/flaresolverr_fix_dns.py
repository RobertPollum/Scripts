"""
Fix DNS for FlareSolverr CT114.
Two issues:
1. CT114 resolv.conf reverted to router DNS (GATEWAY_IP) which blocks torrent sites.
2. Docker container has its own network namespace and doesn't inherit resolv.conf.
Fix: set dhclient to supersede DNS on CT114, recreate Docker container with --dns 1.1.1.1.
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

def pct(vmid, cmd, timeout=60):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}", timeout=timeout)
    return out.read().decode().strip(), err.read().decode().strip()

def host_write(remote_path, content):
    sftp = c.open_sftp()
    with sftp.open("/tmp/_fw_tmp", "w") as f:
        f.write(content)
    sftp.close()
    _, out, err = c.exec_command(f"pct push {FLARE_VMID} /tmp/_fw_tmp {remote_path}")
    out.read(); err.read()

# ── Step 1: Fix CT114 host DNS (same fix as Prowlarr) ────────────────────────
print("=== Step 1: Fix CT114 host DNS ===")
dhclient_conf = """\
supersede domain-name-servers 1.1.1.1, 8.8.8.8;
supersede domain-search "";
supersede domain-name "";

option rfc3442-classless-static-routes code 121 = array of unsigned integer 8;
send host-name = gethostname();
request subnet-mask, broadcast-address, time-offset, routers,
        host-name, netbios-name-servers, netbios-scope, interface-mtu,
        rfc3442-classless-static-routes, ntp-servers;
"""
host_write("/etc/dhcp/dhclient.conf", dhclient_conf)

resolv = "nameserver 1.1.1.1\nnameserver 8.8.8.8\n"
host_write("/etc/resolv.conf", resolv)

# Renew DHCP with new config
pct(FLARE_VMID, "dhclient -r eth0 2>/dev/null; dhclient eth0 2>/dev/null")
time.sleep(3)

out_rc, _ = pct(FLARE_VMID, "cat /etc/resolv.conf")
print(f"  resolv.conf: {out_rc}")

out_dns, _ = pct(FLARE_VMID, "getent hosts 1337x.to 2>&1 | head -2")
print(f"  DNS 1337x.to: {out_dns or 'FAIL'}")

# ── Step 2: Recreate Docker container with explicit --dns ─────────────────────
print("\n=== Step 2: Recreate FlareSolverr Docker container with --dns 1.1.1.1 ===")
pct(FLARE_VMID, "docker stop flaresolverr 2>/dev/null; docker rm flaresolverr 2>/dev/null; true")
time.sleep(3)

run_out, run_err = pct(FLARE_VMID,
    "docker run -d "
    "--name flaresolverr "
    "--restart unless-stopped "
    "-p 8191:8191 "
    "--dns 1.1.1.1 "
    "--dns 8.8.8.8 "
    "-e LOG_LEVEL=info "
    "-e TZ=America/Detroit "
    "ghcr.io/flaresolverr/flaresolverr:latest 2>&1",
    timeout=30)
print(f"  {run_out or run_err}")

print("\n[waiting 12s for FlareSolverr to start...]")
time.sleep(12)

# ── Step 3: Verify Docker container DNS ──────────────────────────────────────
print("\n=== Step 3: Verify Docker container DNS ===")
out_ddns, _ = pct(FLARE_VMID,
    "docker exec flaresolverr cat /etc/resolv.conf 2>/dev/null")
print(f"  Docker resolv.conf: {out_ddns}")

out_dresolve, _ = pct(FLARE_VMID,
    "docker exec flaresolverr nslookup 1337x.to 2>&1 | head -5 || "
    "docker exec flaresolverr getent hosts 1337x.to 2>&1")
print(f"  Docker DNS 1337x.to: {out_dresolve}")

# ── Step 4: Test FlareSolverr solve ──────────────────────────────────────────
print("\n=== Step 4: Test solve request ===")
FLARE_IP = os.environ["FLARESOLVERR_IP"]
for attempt in range(3):
    try:
        r = requests.get(f"http://{FLARE_IP}:8191/", timeout=5)
        print(f"  Health: {r.status_code} {r.json().get('version')}")
        break
    except Exception as e:
        print(f"  Health attempt {attempt+1}: {e}")
        time.sleep(4)

print("\n  Sending solve request (may take 30-60s)...")
try:
    payload = {"cmd": "request.get", "url": "https://1337x.to", "maxTimeout": 60000}
    r2 = requests.post(f"http://{FLARE_IP}:8191/v1",
                       headers={"Content-Type": "application/json"},
                       data=json.dumps(payload), timeout=90)
    result = r2.json()
    sol = result.get("solution", {})
    print(f"  Status: {r2.status_code}")
    print(f"  Solution status: {sol.get('status')}")
    print(f"  URL reached: {sol.get('url','')}")
    resp_snippet = str(sol.get("response", ""))[:200]
    print(f"  Response snippet: {resp_snippet}")
    if result.get("message"):
        print(f"  Message: {result['message'][:300]}")
except Exception as e:
    print(f"  ERROR: {e}")

# Show recent logs
print("\n=== Recent FlareSolverr logs ===")
logs, _ = pct(FLARE_VMID, "docker logs flaresolverr --tail 15 2>&1")
print(logs)

c.close()
print("\nDone.")
