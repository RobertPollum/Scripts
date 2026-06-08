"""
Install Docker + FlareSolverr on CT110, waiting for dpkg lock to clear first.
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

def lxc(vmid, cmd, timeout=15):
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

# ── Step 1: Wait for dpkg lock to clear ───────────────────────────────────────
print("=== Step 1: Wait for dpkg lock ===")
for i in range(24):  # up to 2 min
    locked = lxc("110", "fuser /var/lib/dpkg/lock-frontend 2>/dev/null && echo locked || echo free")
    if "free" in locked:
        print(f"  dpkg free after {i*5}s")
        break
    print(f"  [{i*5}s] still locked (pid: {locked}), waiting...")
    time.sleep(5)

# ── Step 2: Install Docker ─────────────────────────────────────────────────────
print()
print("=== Step 2: Install Docker on CT110 ===")

# Write install script and run via nohup on Proxmox host
install_script = r"""#!/bin/bash
LOG=/tmp/ct110_docker2.log
echo "apt update..." > $LOG
pct exec 110 -- apt-get update -qq >> $LOG 2>&1 && echo "update ok" >> $LOG
echo "apt install docker.io..." >> $LOG
pct exec 110 -- apt-get install -y docker.io >> $LOG 2>&1 && echo "install ok" >> $LOG
echo "enable docker..." >> $LOG
pct exec 110 -- systemctl enable docker >> $LOG 2>&1
pct exec 110 -- systemctl start docker >> $LOG 2>&1 && echo "docker started" >> $LOG
echo "pull flaresolverr..." >> $LOG
pct exec 110 -- docker pull ghcr.io/flaresolverr/flaresolverr:latest >> $LOG 2>&1 && echo "pull ok" >> $LOG
echo "run flaresolverr..." >> $LOG
pct exec 110 -- docker rm -f flaresolverr >> $LOG 2>&1 || true
pct exec 110 -- docker run -d --name flaresolverr --restart unless-stopped \
  -p 8191:8191 -e LOG_LEVEL=info \
  ghcr.io/flaresolverr/flaresolverr:latest >> $LOG 2>&1 && echo "container started" >> $LOG
echo "DONE" >> $LOG
"""
with ssh.open_sftp() as sftp:
    with sftp.file("/tmp/install_ct110_docker2.sh", "w") as f:
        f.write(install_script)
host("chmod +x /tmp/install_ct110_docker2.sh")
host("nohup /tmp/install_ct110_docker2.sh > /tmp/ct110_docker2.log 2>&1 &")
print("  Install script launched in background")

# Poll every 15s
print("  Polling (up to 8 min)...")
for attempt in range(32):
    time.sleep(15)
    tail = host("tail -3 /tmp/ct110_docker2.log 2>/dev/null")
    last = tail.splitlines()[-1] if tail else "..."
    print(f"  [{(attempt+1)*15}s] {last}")
    if "DONE" in tail:
        print("  Install complete!")
        break
    if attempt == 31:
        print("  Timeout. Full log:")
        print(host("cat /tmp/ct110_docker2.log 2>/dev/null"))

# ── Step 3: Verify ────────────────────────────────────────────────────────────
print()
print("=== Step 3: Verify FlareSolverr on CT110 ===")
docker_ver = lxc("110", "docker --version 2>/dev/null || echo 'not found'")
print(f"  Docker: {docker_ver}")

containers = lxc("110", "docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null")
print(f"  Containers: {containers or '(none)'}")

print("  Waiting 15s for container to start...")
time.sleep(15)

health = lxc("110", "curl -s --max-time 8 http://localhost:8191/health 2>/dev/null")
print(f"  Health: {health}")

# ── Step 4: Confirm FlareSolverr uses VPN IP ──────────────────────────────────
print()
print("=== Step 4: Confirm VPN IP alignment ===")
vpn_ip = lxc("110", "curl -s --max-time 6 https://api.ipify.org 2>/dev/null")
flare_ip = lxc("110", 
    "docker exec flaresolverr curl -s --max-time 6 https://api.ipify.org 2>/dev/null",
    timeout=15)
print(f"  CT110 (VPN): {vpn_ip}")
print(f"  FlareSolverr: {flare_ip}")
if vpn_ip and flare_ip and vpn_ip == flare_ip:
    print("  MATCH ✓")
else:
    # Docker may use bridge networking — need host networking
    print("  MISMATCH — restarting with --network host")
    lxc("110", "docker rm -f flaresolverr 2>/dev/null || true")
    lxc("110",
        "docker run -d --name flaresolverr --restart unless-stopped "
        "--network host -e LOG_LEVEL=info "
        "ghcr.io/flaresolverr/flaresolverr:latest",
        timeout=30)
    time.sleep(15)
    health2 = lxc("110", "curl -s --max-time 8 http://localhost:8191/health 2>/dev/null")
    flare_ip2 = lxc("110",
        "docker exec flaresolverr curl -s --max-time 6 https://api.ipify.org 2>/dev/null",
        timeout=15)
    print(f"  Health after host-network restart: {health2}")
    print(f"  FlareSolverr IP now: {flare_ip2}")
    if vpn_ip and flare_ip2 and vpn_ip == flare_ip2:
        print("  MATCH ✓")

# ── Step 5: Update Prowlarr to use CT110 FlareSolverr ────────────────────────
print()
print(f"=== Step 5: Update Prowlarr proxy → http://{_env_prowlarr_ip}:8191 ===")
proxies = get("indexerProxy")
flare_proxy = next((p for p in proxies if "flare" in p.get("implementationName","").lower()), None)
if flare_proxy:
    updated = dict(flare_proxy)
    for f in updated["fields"]:
        if f["name"] == "host":
            f["value"] = f"http://{_env_prowlarr_ip}:8191"
    result, err = put(f"indexerProxy/{flare_proxy['id']}", updated)
    if err:
        print(f"  Error: {err}")
    else:
        new_host = next((f["value"] for f in result.get("fields",[]) if f["name"]=="host"), "")
        print(f"  Updated: {new_host} ✓")

# ── Step 6: Clear CF indexer backoff + test ───────────────────────────────────
print()
print("=== Step 6: Clear backoff + test ===")
db = "/var/lib/prowlarr/prowlarr.db"
lxc("110", f"sqlite3 {db} \"DELETE FROM IndexerStatus;\" 2>/dev/null")
lxc("110", "systemctl restart prowlarr")
print("  Restarted Prowlarr. Waiting 20s...")
time.sleep(20)

for i in range(8):
    try:
        get("health", timeout=8)
        print("  Prowlarr up")
        break
    except:
        time.sleep(4)

# Test CF indexers via Torznab
CF_NAMES = {"eztv", "1337x", "kickasstorrents", "torrentgalaxy"}
indexers = get("indexer")
for idx in [i for i in indexers if any(cf in i["name"].lower() for cf in CF_NAMES) and i.get("enable")]:
    url = f"{PROWLARR}/{idx['id']}/api?t=caps&apikey={KEY}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=40) as r:
            data = r.read()
            print(f"  {idx['name']}: OK ({len(data)} bytes) ✓")
    except urllib.error.HTTPError as e:
        print(f"  {idx['name']}: HTTP {e.code}")
    except Exception as e:
        print(f"  {idx['name']}: {type(e).__name__}: {str(e)[:60]}")
    time.sleep(3)

ssh.close()
print("\nDone.")
