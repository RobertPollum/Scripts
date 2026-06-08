"""
Start FlareSolverr on CT110 via background script (avoids SSH timeout on docker pull).
Then update Prowlarr proxy, fix TorrentGalaxy URL, clear backoff.
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

def lxc(vmid, cmd, timeout=15):
    _, out, _ = ssh.exec_command(f"pct exec {vmid} -- {cmd}", timeout=timeout)
    return out.read().decode(errors="replace").strip()

def host(cmd, timeout=15):
    _, out, _ = ssh.exec_command(cmd, timeout=timeout)
    return out.read().decode(errors="replace").strip()

def prowlarr_get(path, timeout=12):
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, headers={"X-Api-Key": KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def prowlarr_put(path, data, timeout=15):
    body = json.dumps(data).encode()
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, data=body,
                                  headers={"X-Api-Key": KEY, "Content-Type": "application/json"})
    req.get_method = lambda: "PUT"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:200]}"

# ── Step 1: Launch FlareSolverr via background script on Proxmox host ─────────
print("=== Step 1: Launch FlareSolverr on CT110 (background) ===")

script = """#!/bin/bash
LOG=/tmp/ct110_flare.log
echo "Starting..." > $LOG
pct exec 110 -- docker rm -f flaresolverr >> $LOG 2>&1 || true
pct exec 110 -- docker run -d --name flaresolverr --restart unless-stopped \
  --network host \
  -e LOG_LEVEL=info \
  -e HOST=0.0.0.0 \
  -e PORT=8191 \
  ghcr.io/flaresolverr/flaresolverr:latest >> $LOG 2>&1
echo "DONE" >> $LOG
"""
with ssh.open_sftp() as sftp:
    with sftp.file("/tmp/start_flare_ct110.sh", "w") as f:
        f.write(script)
host("chmod +x /tmp/start_flare_ct110.sh")
host("nohup /tmp/start_flare_ct110.sh > /tmp/ct110_flare.log 2>&1 &")
print("  Script launched in background, polling...")

# Poll until done (image may already be cached from previous attempt)
for i in range(24):
    time.sleep(5)
    tail = host("tail -2 /tmp/ct110_flare.log 2>/dev/null")
    last = tail.splitlines()[-1] if tail else "..."
    print(f"  [{(i+1)*5}s] {last}")
    if "DONE" in tail:
        print("  Container started!")
        break
    if "Error" in tail and "already" not in tail:
        print(f"  Error detected: {tail}")
        break
else:
    print("  Timed out — checking status anyway")

print()
print("  Full log:")
print(host("cat /tmp/ct110_flare.log 2>/dev/null"))

# ── Step 2: Wait for FlareSolverr to be healthy ────────────────────────────────
print()
print("=== Step 2: FlareSolverr health on CT110 ===")
status = lxc("110", "docker ps --filter name=flaresolverr --format '{{.Names}} {{.Status}}'")
print(f"  Container: {status or '(not found)'}")

print("  Waiting 15s for initialization...")
time.sleep(15)

for attempt in range(6):
    health = lxc("110", "curl -s --max-time 6 http://localhost:8191/health 2>/dev/null")
    if '"ok"' in (health or ""):
        print(f"  Health: {health} ✓")
        break
    print(f"  [{attempt*5}s] not ready yet: {health}")
    time.sleep(5)
else:
    print("  WARNING: FlareSolverr not healthy — check docker logs")
    print(lxc("110", "docker logs --tail 20 flaresolverr 2>/dev/null", timeout=10))

# ── Step 3: Confirm FlareSolverr uses VPN IP ──────────────────────────────────
print()
print("=== Step 3: IP alignment check ===")
vpn_ip = lxc("110", "curl -s --max-time 6 https://api.ipify.org 2>/dev/null")
raw = lxc("110",
    "curl -s --max-time 20 -X POST http://localhost:8191/v1 "
    "-H 'Content-Type: application/json' "
    "-d '{\"cmd\":\"request.get\",\"url\":\"https://api.ipify.org\",\"maxTimeout\":15000}' 2>/dev/null",
    timeout=25)
try:
    flare_ip = json.loads(raw).get("solution", {}).get("response", "").strip()
except Exception:
    flare_ip = f"(parse err: {raw[:50]})"

print(f"  CT110 VPN IP     : {vpn_ip}")
print(f"  FlareSolverr IP  : {flare_ip}")
if vpn_ip and flare_ip and vpn_ip == flare_ip:
    print("  MATCH ✓ — same exit IP")
else:
    print("  MISMATCH — host networking may not have applied")
    net_mode = lxc("110", "docker inspect flaresolverr --format '{{.HostConfig.NetworkMode}}' 2>/dev/null")
    print(f"  NetworkMode: {net_mode}")

# ── Step 4: Update Prowlarr proxy to CT110 ────────────────────────────────────
print()
print(f"=== Step 4: Update Prowlarr proxy → http://{_env_prowlarr_ip}:8191 ===")
proxies = prowlarr_get("indexerProxy")
flare_proxy = next((p for p in proxies if "flare" in p.get("implementationName", "").lower()), None)

if flare_proxy:
    current = next((f["value"] for f in flare_proxy.get("fields", []) if f["name"] == "host"), "")
    print(f"  Current: {current}")
    updated = dict(flare_proxy)
    for f in updated["fields"]:
        if f["name"] == "host":
            f["value"] = f"http://{_env_prowlarr_ip}:8191"
    result, err = prowlarr_put(f"indexerProxy/{flare_proxy['id']}", updated)
    if err:
        print(f"  PUT error: {err[:150]}")
    else:
        new = next((f["value"] for f in result.get("fields", []) if f["name"] == "host"), "")
        print(f"  Updated: {new} ✓")

# ── Step 5: Fix TorrentGalaxyClone base URL ───────────────────────────────────
print()
print("=== Step 5: Fix TorrentGalaxyClone base URL ===")
# Test which URL works
working_tgc_url = None
for url in ["https://torrentgalaxy.to/", "https://torrentgalaxy.info/"]:
    r = lxc("110", f"curl -sL --max-time 8 -o /dev/null -w '%{{http_code}}' '{url}' 2>/dev/null", timeout=12)
    print(f"  {url}: HTTP {r}")
    if r in ("200", "301", "302") and not working_tgc_url:
        working_tgc_url = url

indexers = prowlarr_get("indexer")
tgc = next((i for i in indexers if "torrentgalaxy" in i["name"].lower()), None)
if tgc and working_tgc_url:
    current_base = next((f.get("value") for f in tgc.get("fields", []) if f.get("name") == "baseUrl"), None)
    print(f"  Current baseUrl: {current_base}")
    if current_base != working_tgc_url:
        updated = dict(tgc)
        for f in updated["fields"]:
            if f.get("name") == "baseUrl":
                f["value"] = working_tgc_url
        result, err = prowlarr_put(f"indexer/{tgc['id']}", updated, timeout=30)
        if err:
            print(f"  PUT error: {err[:150]}")
        else:
            new_base = next((f.get("value") for f in result.get("fields", []) if f.get("name") == "baseUrl"), "")
            print(f"  Updated: {new_base} ✓")
    else:
        print(f"  Already correct ✓")

# ── Step 6: Clear all backoff ─────────────────────────────────────────────────
print()
print("=== Step 6: Clear backoff + restart Prowlarr ===")
db = "/var/lib/prowlarr/prowlarr.db"
lxc("110", f"sqlite3 {db} 'DELETE FROM IndexerStatus;'")
lxc("110", "systemctl restart prowlarr")
print("  Waiting 20s...")
time.sleep(20)
for _ in range(8):
    try:
        prowlarr_get("health", timeout=8)
        print("  Prowlarr up")
        break
    except:
        time.sleep(4)

# ── Step 7: Test CF indexers ──────────────────────────────────────────────────
print()
print("=== Step 7: CF indexer tests ===")
CF_NAMES = {"eztv", "1337x", "kickasstorrents", "torrentgalaxy", "torrentdownloads"}
time.sleep(3)
indexers2 = prowlarr_get("indexer")
cf_idxs = [i for i in indexers2 if any(cf in i["name"].lower() for cf in CF_NAMES) and i.get("enable")]
for idx in sorted(cf_idxs, key=lambda x: x["name"]):
    url = f"{PROWLARR}/{idx['id']}/api?t=caps&apikey={KEY}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=40) as r:
            data = r.read()
            print(f"  ✓ {idx['name']} ({len(data)}b)")
    except urllib.error.HTTPError as e:
        print(f"  ✗ {idx['name']}: HTTP {e.code}")
    except Exception as e:
        print(f"  ✗ {idx['name']}: {str(e)[:70]}")
    time.sleep(2)

# ── Step 8: Update watchdog to monitor FlareSolverr ──────────────────────────
print()
print("=== Step 8: Update watchdog ===")
current_wd = lxc("110", "cat /usr/local/bin/vpn-watchdog.sh")
if "flaresolverr" not in current_wd:
    flare_block = (
        '\n# Ensure FlareSolverr container is running\n'
        'if ! docker ps --filter name=flaresolverr --filter status=running -q | grep -q .; then\n'
        '    log "WARN: flaresolverr not running, restarting"\n'
        '    docker start flaresolverr 2>/dev/null || \\\n'
        '    docker run -d --name flaresolverr --restart unless-stopped \\\n'
        '        --network host -e LOG_LEVEL=info -e HOST=0.0.0.0 -e PORT=8191 \\\n'
        '        ghcr.io/flaresolverr/flaresolverr:latest 2>/dev/null\n'
        '    log "INFO: flaresolverr restarted"\n'
        'fi\n'
    )
    new_wd = current_wd.rstrip() + flare_block
    with ssh.open_sftp() as sftp:
        with sftp.file("/tmp/vpn-watchdog-updated.sh", "w") as f:
            f.write(new_wd)
    host("pct push 110 /tmp/vpn-watchdog-updated.sh /usr/local/bin/vpn-watchdog.sh")
    lxc("110", "chmod +x /usr/local/bin/vpn-watchdog.sh")
    print("  Watchdog updated ✓")
else:
    print("  Already monitors FlareSolverr ✓")

ssh.close()
print("\nDone.")
