"""
Fix CF indexers by:
1. Installing FlareSolverr directly on CT110 (shares VPN IP with Prowlarr)
2. Updating Prowlarr to point to the new local FlareSolverr at localhost:8191
3. Fixing TorrentGalaxyClone base URL
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

def lxc(vmid, cmd, timeout=60):
    _, out, err = ssh.exec_command(f"pct exec {vmid} -- {cmd}", timeout=timeout)
    stdout = out.read().decode(errors="replace").strip()
    stderr = "\n".join(l for l in err.read().decode(errors="replace").splitlines()
                       if "deprecated" not in l.lower()).strip()
    return stdout or stderr

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

# ── Step 1: Check if Docker is available on CT110 ─────────────────────────────
print("=== Step 1: Check CT110 for Docker ===")
docker_check = lxc("110", "docker --version 2>/dev/null || echo 'not installed'")
print(f"  {docker_check}")

has_docker = "Docker" in docker_check

if not has_docker:
    print("  Installing Docker on CT110...")
    # CT110 is Debian-based
    steps = [
        "apt-get update -qq",
        "apt-get install -y -qq docker.io",
        "systemctl enable docker && systemctl start docker",
    ]
    for step in steps:
        r = lxc("110", step, timeout=120)
        print(f"    {step[:40]}: {r[-50:] if r else 'ok'}")
    
    docker_check = lxc("110", "docker --version 2>/dev/null || echo 'failed'")
    print(f"  After install: {docker_check}")
    has_docker = "Docker" in docker_check

# ── Step 2: Run FlareSolverr on CT110 ─────────────────────────────────────────
print()
print("=== Step 2: FlareSolverr on CT110 (local to VPN) ===")

# Check if already running
existing = lxc("110", "docker ps --filter name=flaresolverr --format '{{.Names}} {{.Status}}' 2>/dev/null")
print(f"  Existing: {existing or '(none)'}")

if "flaresolverr" not in (existing or "").lower():
    print("  Starting FlareSolverr on CT110...")
    # Stop any old one first
    lxc("110", "docker rm -f flaresolverr 2>/dev/null || true")
    run_cmd = (
        "docker run -d --name flaresolverr --restart unless-stopped "
        "-p 127.0.0.1:8191:8191 "
        "-e LOG_LEVEL=info "
        "ghcr.io/flaresolverr/flaresolverr:latest"
    )
    result = lxc("110", run_cmd, timeout=120)
    print(f"  Result: {result[:80]}")
    print("  Waiting 15s for container to start...")
    time.sleep(15)

# Verify it's running
status = lxc("110", "docker ps --filter name=flaresolverr --format '{{.Names}} {{.Status}}' 2>/dev/null")
print(f"  Container: {status}")

# Health check - from localhost inside CT110
health = lxc("110", "curl -s --max-time 8 http://127.0.0.1:8191/health 2>/dev/null")
print(f"  Health: {health}")

if '"ok"' not in (health or ""):
    print("  WARNING: FlareSolverr not healthy yet, waiting more...")
    time.sleep(20)
    health = lxc("110", "curl -s --max-time 8 http://127.0.0.1:8191/health 2>/dev/null")
    print(f"  Health retry: {health}")

# ── Step 3: Update Prowlarr proxy to point to localhost:8191 ──────────────────
print()
print("=== Step 3: Update Prowlarr FlareSolverr proxy URL ===")
proxies = get("indexerProxy")
flare = next((p for p in proxies if "flare" in p.get("implementationName","").lower()), None)

if flare:
    current_host = next((f["value"] for f in flare.get("fields",[]) if f["name"]=="host"), "")
    print(f"  Current host: {current_host}")
    
    if current_host != f"http://{_env_prowlarr_ip}:8191":
        updated = dict(flare)
        for f in updated["fields"]:
            if f["name"] == "host":
                f["value"] = f"http://{_env_prowlarr_ip}:8191"
        result, err = put(f"indexerProxy/{flare['id']}", updated)
        if err:
            print(f"  PUT error: {err}")
        else:
            new_host = next((f["value"] for f in result.get("fields",[]) if f["name"]=="host"), "")
            print(f"  Updated host: {new_host}")
    else:
        print("  Already pointing to CT110 localhost ✓")

# ── Step 4: Fix TorrentGalaxyClone URL ────────────────────────────────────────
print()
print("=== Step 4: Fix TorrentGalaxyClone definition URL ===")
tgc_def = lxc("110", "cat /var/lib/prowlarr/Definitions/torrentgalaxyclone.yml 2>/dev/null | grep -A5 'links:\\|legacylinks:'")
print(f"  Definition links:\n  {tgc_def}")

# Check what URL it's currently using and if torrentgalaxy.to works
for url in ["https://torrentgalaxy.to", "https://torrentgalaxy.one", "https://torrentgalaxy.info"]:
    r = lxc("110", f"curl -sL --max-time 8 -o /dev/null -w '%{{http_code}} %{{url_effective}}' '{url}' 2>/dev/null", timeout=15)
    print(f"  {url}: {r}")

# ── Step 5: Test FlareSolverr on CT110 actually uses VPN IP ───────────────────
print()
print("=== Step 5: Verify FlareSolverr on CT110 uses VPN exit IP ===")
# Ask FlareSolverr to fetch an IP check URL
ip_check = lxc("110",
    "curl -s --max-time 20 -X POST http://127.0.0.1:8191/v1 "
    "-H 'Content-Type: application/json' "
    "-d '{\"cmd\":\"request.get\",\"url\":\"https://api.ipify.org\",\"maxTimeout\":15000}' "
    "2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin); "
    "print('FlareSolverr IP:', d.get('solution',{}).get('response','?').strip())\" 2>/dev/null",
    timeout=30)
print(f"  {ip_check}")

vpn_ip = lxc("110", "curl -s --max-time 5 https://api.ipify.org 2>/dev/null")
print(f"  CT110 VPN IP: {vpn_ip}")

# ── Step 6: Quick test of 1337x through local FlareSolverr ────────────────────
print()
print("=== Step 6: Test 1337x through CT110 FlareSolverr ===")
solve_result = lxc("110",
    "curl -s --max-time 35 -X POST http://127.0.0.1:8191/v1 "
    "-H 'Content-Type: application/json' "
    "-d '{\"cmd\":\"request.get\",\"url\":\"https://1337x.to/cat/Movies/1/\",\"maxTimeout\":30000}' "
    "2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin); "
    "sol=d.get('solution',{}); "
    "print('status=' + d.get('status','?') + ' http=' + str(sol.get('status','?')) + ' len=' + str(len(sol.get('response',''))))\" 2>/dev/null",
    timeout=45)
print(f"  {solve_result}")

ssh.close()
print()
print("Done. Now go to Prowlarr UI → Settings → Indexers → Test each CF indexer.")
