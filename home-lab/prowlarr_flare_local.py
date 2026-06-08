"""
Install Docker + FlareSolverr on CT110 via a background script on Proxmox host.
Polls until done, then updates Prowlarr proxy URL.
"""
import paramiko, os, time, urllib.request, json, urllib.error
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

def lxc_quick(vmid, cmd, timeout=15):
    _, out, _ = ssh.exec_command(f"pct exec {vmid} -- {cmd}", timeout=timeout)
    return out.read().decode(errors="replace").strip()

def get(path, timeout=15):
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, headers={"X-Api-Key": KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def put(path, data, timeout=15):
    body = json.dumps(data).encode()
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, data=body,
                                  headers={"X-Api-Key": KEY, "Content-Type": "application/json"})
    req.get_method = lambda: "PUT"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:200]}"

# ── Step 1: Write install script to Proxmox host and run in background ────────
install_script = """#!/bin/bash
set -e
LOG=/tmp/ct110_docker_install.log
echo "Starting Docker install on CT110..." > $LOG

# Install docker.io
pct exec 110 -- apt-get update -qq >> $LOG 2>&1
pct exec 110 -- apt-get install -y docker.io >> $LOG 2>&1
pct exec 110 -- systemctl enable docker >> $LOG 2>&1
pct exec 110 -- systemctl start docker >> $LOG 2>&1

echo "Docker installed. Starting FlareSolverr..." >> $LOG

# Pull and run FlareSolverr bound to 0.0.0.0:8191 on CT110
pct exec 110 -- docker rm -f flaresolverr 2>/dev/null || true
pct exec 110 -- docker run -d --name flaresolverr --restart unless-stopped \\
  -p 8191:8191 \\
  -e LOG_LEVEL=info \\
  ghcr.io/flaresolverr/flaresolverr:latest >> $LOG 2>&1

echo "DONE" >> $LOG
"""

print("=== Step 1: Writing install script to Proxmox host ===")
with ssh.open_sftp() as sftp:
    with sftp.file("/tmp/install_ct110_docker.sh", "w") as f:
        f.write(install_script)
host("chmod +x /tmp/install_ct110_docker.sh")
print("  Script written.")

# Run in background
print("  Launching install in background (nohup)...")
host("nohup /tmp/install_ct110_docker.sh > /tmp/ct110_docker_install.log 2>&1 &")
print("  Background job started. Polling log...")

# ── Step 2: Poll until DONE ───────────────────────────────────────────────────
print()
print("=== Step 2: Waiting for install to complete ===")
for attempt in range(40):  # up to ~6 min
    time.sleep(10)
    log_tail = host("tail -5 /tmp/ct110_docker_install.log 2>/dev/null")
    print(f"  [{attempt*10}s] {log_tail.splitlines()[-1] if log_tail else '...'}")
    if "DONE" in log_tail:
        print("  Install complete!")
        break
    if "Error" in log_tail or "error" in log_tail:
        print(f"  Possible error detected: {log_tail}")
        break
else:
    print("  Timed out waiting. Checking status...")

print()
print("  Full install log:")
print(host("cat /tmp/ct110_docker_install.log 2>/dev/null"))

# ── Step 3: Verify Docker + FlareSolverr on CT110 ────────────────────────────
print()
print("=== Step 3: Verify FlareSolverr on CT110 ===")
docker_ver = lxc_quick("110", "docker --version 2>/dev/null || echo 'not found'")
print(f"  Docker: {docker_ver}")

containers = lxc_quick("110", "docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null")
print(f"  Containers: {containers}")

# Wait a bit for container to start
time.sleep(10)
health = lxc_quick("110", "curl -s --max-time 8 http://localhost:8191/health 2>/dev/null")
print(f"  Health (localhost:8191): {health}")

if '"ok"' not in (health or ""):
    print("  Waiting 20s more for FlareSolverr to initialize...")
    time.sleep(20)
    health = lxc_quick("110", "curl -s --max-time 8 http://localhost:8191/health 2>/dev/null")
    print(f"  Health retry: {health}")

# ── Step 4: Update Prowlarr proxy to use CT110's local FlareSolverr ───────────
print()
print(f"=== Step 4: Update Prowlarr proxy to http://{_env_prowlarr_ip}:8191 ===")
proxies = get("indexerProxy")
flare = next((p for p in proxies if "flare" in p.get("implementationName","").lower()), None)

if not flare:
    print("  ERROR: No FlareSolverr proxy in Prowlarr")
else:
    current = next((f["value"] for f in flare.get("fields",[]) if f["name"]=="host"), "")
    print(f"  Current: {current}")
    updated = dict(flare)
    for f in updated["fields"]:
        if f["name"] == "host":
            f["value"] = f"http://{_env_prowlarr_ip}:8191"
    result, err = put(f"indexerProxy/{flare['id']}", updated)
    if err:
        print(f"  PUT error: {err}")
    else:
        new_host = next((f["value"] for f in result.get("fields",[]) if f["name"]=="host"), "")
        print(f"  Updated to: {new_host} ✓")

# ── Step 5: Verify FlareSolverr uses VPN IP ───────────────────────────────────
print()
print("=== Step 5: Verify FlareSolverr sees VPN IP ===")
vpn_ip = lxc_quick("110", "curl -s --max-time 6 https://api.ipify.org 2>/dev/null")
print(f"  CT110 VPN exit IP: {vpn_ip}")

flare_ip_cmd = (
    "docker exec flaresolverr sh -c "
    "\"curl -s --max-time 6 https://api.ipify.org 2>/dev/null\" 2>/dev/null"
)
flare_ip = lxc_quick("110", flare_ip_cmd, timeout=15)
print(f"  FlareSolverr container IP: {flare_ip}")

if vpn_ip and flare_ip and vpn_ip == flare_ip:
    print("  MATCH — both using VPN IP ✓")
else:
    print("  WARNING: IPs differ — check Docker networking")

# ── Step 6: Quick functional test through FlareSolverr on CT110 ──────────────
print()
print("=== Step 6: Test 1337x solve via CT110 FlareSolverr ===")
# Use the SSH connection to run curl on CT110 since it's localhost
test_cmd = (
    "curl -s --max-time 35 -X POST http://localhost:8191/v1 "
    "-H 'Content-Type: application/json' "
    "-d '{\"cmd\":\"request.get\",\"url\":\"https://1337x.to/cat/Movies/1/\",\"maxTimeout\":30000}' "
    "2>/dev/null | python3 -c \""
    "import sys,json; d=json.load(sys.stdin); sol=d.get('solution',{}); "
    "cf=('Just a moment' in sol.get('response','') or 'cf-browser-verification' in sol.get('response','')); "
    "print('status=' + d.get('status','?') + ' http=' + str(sol.get('status','?')) + "
    "' still_cf=' + str(cf) + ' len=' + str(len(sol.get('response',''))))\" 2>/dev/null"
)
result = lxc_quick("110", test_cmd, timeout=45)
print(f"  {result}")

ssh.close()
print()
print("Done. Check Prowlarr UI — CF indexers should now work.")
