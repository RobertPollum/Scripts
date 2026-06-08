"""
1. Start FlareSolverr on CT110 (Docker already installed, nesting=1)
2. Update Prowlarr proxy to point to CT110's local FlareSolverr
3. Fix TorrentGalaxyClone base URL
4. Clear backoff and verify all CF indexers work
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

def lxc(vmid, cmd, timeout=20):
    _, out, _ = ssh.exec_command(f"pct exec {vmid} -- {cmd}", timeout=timeout)
    return out.read().decode(errors="replace").strip()

def host(cmd, timeout=20):
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

# ── Step 1: Start FlareSolverr on CT110 with host networking ─────────────────
print("=== Step 1: Start FlareSolverr on CT110 ===")

# Remove any old container
lxc("110", "docker rm -f flaresolverr 2>/dev/null || true")

# Use --network host so FlareSolverr inherits CT110's VPN routing
run_result = lxc("110",
    "docker run -d --name flaresolverr --restart unless-stopped "
    "--network host "
    "-e LOG_LEVEL=info "
    "-e HOST=0.0.0.0 "
    "-e PORT=8191 "
    "ghcr.io/flaresolverr/flaresolverr:latest",
    timeout=60)
print(f"  docker run: {run_result[:80]}")

print("  Waiting 20s for container to initialize...")
time.sleep(20)

# Check it's running
status = lxc("110", "docker ps --filter name=flaresolverr --format '{{.Names}} {{.Status}}'")
print(f"  Container: {status}")

# Health check from localhost
health = lxc("110", "curl -s --max-time 8 http://localhost:8191/health 2>/dev/null")
print(f"  Health (localhost:8191): {health}")

if '"ok"' not in (health or ""):
    print("  Not healthy yet, waiting 15s more...")
    time.sleep(15)
    health = lxc("110", "curl -s --max-time 8 http://localhost:8191/health 2>/dev/null")
    print(f"  Health retry: {health}")

# ── Step 2: Confirm FlareSolverr uses VPN IP ─────────────────────────────────
print()
print("=== Step 2: Verify FlareSolverr uses same IP as CT110 ===")
vpn_ip = lxc("110", "curl -s --max-time 6 https://api.ipify.org 2>/dev/null")

# Ask FlareSolverr to fetch an IP check URL
flare_ip_cmd = (
    "curl -s --max-time 20 -X POST http://localhost:8191/v1 "
    "-H 'Content-Type: application/json' "
    "-d '{\"cmd\":\"request.get\",\"url\":\"https://api.ipify.org\",\"maxTimeout\":15000}' 2>/dev/null"
)
raw = lxc("110", flare_ip_cmd, timeout=30)
try:
    flare_ip = json.loads(raw).get("solution", {}).get("response", "").strip()
except Exception:
    flare_ip = f"parse error: {raw[:60]}"

print(f"  CT110 VPN exit IP : {vpn_ip}")
print(f"  FlareSolverr IP   : {flare_ip}")
if vpn_ip and flare_ip and vpn_ip == flare_ip:
    print("  MATCH — same VPN IP ✓")
else:
    print("  MISMATCH — Docker may not be using host network")
    # Show docker network inspect
    net = lxc("110", "docker inspect flaresolverr --format '{{.HostConfig.NetworkMode}}'")
    print(f"  Network mode: {net}")

# ── Step 3: Test CF solve actually works from VPN IP ─────────────────────────
print()
print("=== Step 3: Test CF solve for 1337x from CT110 ===")
solve_cmd = (
    "curl -s --max-time 35 -X POST http://localhost:8191/v1 "
    "-H 'Content-Type: application/json' "
    "-d '{\"cmd\":\"request.get\",\"url\":\"https://1337x.to/cat/Movies/1/\",\"maxTimeout\":30000}' 2>/dev/null"
)
raw2 = lxc("110", solve_cmd, timeout=45)
try:
    d = json.loads(raw2)
    sol = d.get("solution", {})
    still_cf = "just a moment" in sol.get("response", "").lower()
    print(f"  status={d.get('status')} http={sol.get('status')} still_cf={still_cf} len={len(sol.get('response',''))}")
    if d.get("status") == "ok" and not still_cf:
        print("  CF challenge solved ✓")
    else:
        print(f"  Issue: {d.get('message', 'unknown')[:100]}")
except Exception as e:
    print(f"  Parse error: {e} — raw: {raw2[:100]}")

# ── Step 4: Update Prowlarr proxy to CT110 local FlareSolverr ─────────────────
print()
print(f"=== Step 4: Update Prowlarr proxy → http://{_env_prowlarr_ip}:8191 ===")
proxies = prowlarr_get("indexerProxy")
flare_proxy = next((p for p in proxies if "flare" in p.get("implementationName", "").lower()), None)

if not flare_proxy:
    print("  ERROR: No FlareSolverr proxy in Prowlarr")
else:
    current_host = next((f["value"] for f in flare_proxy.get("fields", []) if f["name"] == "host"), "")
    print(f"  Current: {current_host}")
    
    updated = dict(flare_proxy)
    for f in updated["fields"]:
        if f["name"] == "host":
            f["value"] = f"http://{_env_prowlarr_ip}:8191"
    
    result, err = prowlarr_put(f"indexerProxy/{flare_proxy['id']}", updated)
    if err:
        print(f"  PUT error: {err[:150]}")
    else:
        new_host = next((f["value"] for f in result.get("fields", []) if f["name"] == "host"), "")
        print(f"  Updated: {new_host} ✓")

# ── Step 5: Fix TorrentGalaxyClone URL via Prowlarr indexer settings ──────────
print()
print("=== Step 5: Fix TorrentGalaxyClone URL ===")
# Check what URLs the definition file lists
urls_in_def = lxc("110",
    "grep -A 10 '^links:' /var/lib/prowlarr/Definitions/torrentgalaxyclone.yml 2>/dev/null | head -10")
print(f"  Definition links:\n  {urls_in_def}")

# Check which actually works
for url in ["https://torrentgalaxy.to/", "https://torrentgalaxy.one/", "https://torrentgalaxy.info/"]:
    r = lxc("110", f"curl -sL --max-time 8 -o /dev/null -w '%{{http_code}} %{{url_effective}}' '{url}' 2>/dev/null", timeout=15)
    print(f"  {url}: {r}")

# Get TorrentGalaxyClone indexer and update its baseUrl field via API
indexers = prowlarr_get("indexer")
tgc = next((i for i in indexers if "torrentgalaxy" in i["name"].lower()), None)
if tgc:
    # Find baseUrl field
    base_url_field = next((f for f in tgc.get("fields", []) if f.get("name") == "baseUrl"), None)
    current_base = base_url_field.get("value") if base_url_field else None
    print(f"\n  Current baseUrl: {current_base}")
    
    # Update to torrentgalaxy.to if not already
    if current_base != "https://torrentgalaxy.to/":
        updated_tgc = dict(tgc)
        for f in updated_tgc["fields"]:
            if f.get("name") == "baseUrl":
                f["value"] = "https://torrentgalaxy.to/"
        result, err = prowlarr_put(f"indexer/{tgc['id']}", updated_tgc, timeout=30)
        if err:
            print(f"  PUT error: {err[:150]}")
        else:
            new_base = next((f.get("value") for f in result.get("fields", []) if f.get("name") == "baseUrl"), "")
            print(f"  Updated baseUrl: {new_base} ✓")
    else:
        print("  Already set to torrentgalaxy.to ✓")

# ── Step 6: Clear all backoff and restart Prowlarr ────────────────────────────
print()
print("=== Step 6: Clear backoff + restart Prowlarr ===")
db = "/var/lib/prowlarr/prowlarr.db"
lxc("110", f"sqlite3 {db} 'DELETE FROM IndexerStatus;' && echo cleared")
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

# ── Step 7: Test all CF indexers via Torznab ─────────────────────────────────
print()
print("=== Step 7: CF indexer Torznab tests ===")
CF_NAMES = {"eztv", "1337x", "kickasstorrents", "torrentgalaxy", "torrentdownloads"}
indexers2 = prowlarr_get("indexer")
cf_idxs = [i for i in indexers2 if any(cf in i["name"].lower() for cf in CF_NAMES) and i.get("enable")]

for idx in cf_idxs:
    url = f"{PROWLARR}/{idx['id']}/api?t=caps&apikey={KEY}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=40) as r:
            data = r.read()
            print(f"  ✓ {idx['name']} ({len(data)}b)")
    except urllib.error.HTTPError as e:
        print(f"  ✗ {idx['name']}: HTTP {e.code}")
    except Exception as e:
        print(f"  ✗ {idx['name']}: {str(e)[:70]}")
    time.sleep(2)

# ── Step 8: Update watchdog to also restart FlareSolverr if it dies ──────────
print()
print("=== Step 8: Update watchdog to monitor FlareSolverr container ===")
watchdog_addition = r"""
# Also ensure FlareSolverr container is running on CT110
if ! docker ps --filter name=flaresolverr --filter status=running -q | grep -q .; then
    log "WARN: flaresolverr container not running, restarting"
    docker start flaresolverr 2>/dev/null || \
    docker run -d --name flaresolverr --restart unless-stopped \
        --network host -e LOG_LEVEL=info -e HOST=0.0.0.0 -e PORT=8191 \
        ghcr.io/flaresolverr/flaresolverr:latest
    log "INFO: flaresolverr restarted"
fi
"""

# Read current watchdog, insert before last fi
current_wd = lxc("110", "cat /usr/local/bin/vpn-watchdog.sh")
if "flaresolverr" not in current_wd:
    # Append before the final empty line / end
    new_wd = current_wd.rstrip() + "\n" + watchdog_addition + "\n"
    with ssh.open_sftp() as sftp:
        with sftp.file("/tmp/vpn-watchdog-new.sh", "w") as f:
            f.write(new_wd)
    host("pct push 110 /tmp/vpn-watchdog-new.sh /usr/local/bin/vpn-watchdog.sh")
    lxc("110", "chmod +x /usr/local/bin/vpn-watchdog.sh")
    print("  Watchdog updated to monitor FlareSolverr ✓")
else:
    print("  Watchdog already monitors FlareSolverr ✓")

ssh.close()
print("\nDone.")
