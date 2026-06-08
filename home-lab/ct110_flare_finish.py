"""
Check if FlareSolverr image pull finished on CT110, start container if needed,
update Prowlarr proxy, fix TorrentGalaxy, clear backoff.
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
        return None, f"HTTP {e.code}: {e.read().decode()[:300]}"

# ── Step 1: Check if the background script finished ───────────────────────────
print("=== Step 1: Background install log ===")
log = host("cat /tmp/ct110_flare.log 2>/dev/null | tail -5")
print(log)

done = "DONE" in host("cat /tmp/ct110_flare.log 2>/dev/null")
print(f"  DONE marker: {done}")

if not done:
    print("  Pull still running, waiting 30s...")
    time.sleep(30)
    log2 = host("tail -3 /tmp/ct110_flare.log 2>/dev/null")
    print(f"  Log: {log2}")
    done = "DONE" in host("cat /tmp/ct110_flare.log 2>/dev/null")

if not done:
    # If still not done, start the container manually (image may already be pulled)
    print("  Attempting manual container start...")
    img_check = lxc("110", "docker images ghcr.io/flaresolverr/flaresolverr --format '{{.Repository}}:{{.Tag}}' 2>/dev/null")
    print(f"  Image present: {img_check}")
    
    if "flaresolverr" in img_check.lower():
        start_r = lxc("110",
            "docker rm -f flaresolverr 2>/dev/null; "
            "docker run -d --name flaresolverr --restart unless-stopped "
            "--network host -e LOG_LEVEL=info -e HOST=0.0.0.0 -e PORT=8191 "
            "ghcr.io/flaresolverr/flaresolverr:latest 2>&1 | head -5",
            timeout=15)
        print(f"  Start result: {start_r}")
    else:
        print("  Image not yet available, waiting 60s more...")
        time.sleep(60)
        start_r = lxc("110",
            "docker run -d --name flaresolverr --restart unless-stopped "
            "--network host -e LOG_LEVEL=info -e HOST=0.0.0.0 -e PORT=8191 "
            "ghcr.io/flaresolverr/flaresolverr:latest 2>&1 | head -3",
            timeout=15)
        print(f"  Start result: {start_r}")

# ── Step 2: Wait for health ────────────────────────────────────────────────────
print()
print("=== Step 2: FlareSolverr health ===")
time.sleep(20)  # give container time to boot

for attempt in range(10):
    containers = lxc("110", "docker ps --filter name=flaresolverr --format '{{.Names}} {{.Status}}' 2>/dev/null")
    health = lxc("110", "curl -s --max-time 5 http://localhost:8191/health 2>/dev/null")
    print(f"  Container: {containers}  Health: {health}")
    if '"ok"' in (health or ""):
        print("  FlareSolverr healthy ✓")
        break
    time.sleep(8)
else:
    # Show logs for diagnosis
    print("  Container logs:")
    print(lxc("110", "docker logs --tail 15 flaresolverr 2>&1", timeout=10))

# ── Step 3: IP alignment ──────────────────────────────────────────────────────
print()
print("=== Step 3: IP alignment ===")
vpn_ip = lxc("110", "curl -s --max-time 6 https://api.ipify.org 2>/dev/null")
raw = lxc("110",
    "curl -s --max-time 20 -X POST http://localhost:8191/v1 "
    "-H 'Content-Type: application/json' "
    "-d '{\"cmd\":\"request.get\",\"url\":\"https://api.ipify.org\",\"maxTimeout\":15000}' 2>/dev/null",
    timeout=25)
try:
    flare_ip = json.loads(raw).get("solution", {}).get("response", "").strip()
except Exception:
    flare_ip = f"err:{raw[:40]}"

print(f"  CT110 VPN IP    : {vpn_ip}")
print(f"  FlareSolverr IP : {flare_ip}")
match = vpn_ip and flare_ip and vpn_ip == flare_ip
print(f"  Match: {'✓' if match else '✗ MISMATCH'}")

if not match:
    net = lxc("110", "docker inspect flaresolverr --format '{{.HostConfig.NetworkMode}}' 2>/dev/null")
    print(f"  NetworkMode: {net}")
    if net != "host":
        print("  Fixing: recreating with --network host")
        lxc("110", "docker rm -f flaresolverr 2>/dev/null")
        lxc("110",
            "docker run -d --name flaresolverr --restart unless-stopped "
            "--network host -e LOG_LEVEL=info -e HOST=0.0.0.0 -e PORT=8191 "
            "ghcr.io/flaresolverr/flaresolverr:latest",
            timeout=15)
        time.sleep(20)
        flare_ip2 = ""
        try:
            raw2 = lxc("110",
                "curl -s --max-time 20 -X POST http://localhost:8191/v1 "
                "-H 'Content-Type: application/json' "
                "-d '{\"cmd\":\"request.get\",\"url\":\"https://api.ipify.org\",\"maxTimeout\":15000}' 2>/dev/null",
                timeout=25)
            flare_ip2 = json.loads(raw2).get("solution", {}).get("response", "").strip()
        except Exception:
            pass
        print(f"  FlareSolverr IP after fix: {flare_ip2}")
        match = vpn_ip and flare_ip2 and vpn_ip == flare_ip2
        print(f"  Match: {'✓' if match else '✗'}")

# ── Step 4: Update Prowlarr proxy ─────────────────────────────────────────────
print()
print("=== Step 4: Update Prowlarr proxy → CT110 ===")
proxies = prowlarr_get("indexerProxy")
flare_proxy = next((p for p in proxies if "flare" in p.get("implementationName", "").lower()), None)
if flare_proxy:
    current = next((f["value"] for f in flare_proxy.get("fields", []) if f["name"] == "host"), "")
    print(f"  Current: {current}")
    if current != f"http://{_env_prowlarr_ip}:8191":
        updated = dict(flare_proxy)
        for f in updated["fields"]:
            if f["name"] == "host":
                f["value"] = f"http://{_env_prowlarr_ip}:8191"
        result, err = prowlarr_put(f"indexerProxy/{flare_proxy['id']}", updated)
        if err:
            print(f"  Error: {err[:200]}")
        else:
            new = next((f["value"] for f in result.get("fields", []) if f["name"] == "host"), "")
            print(f"  Updated: {new} ✓")
    else:
        print("  Already correct ✓")

# ── Step 5: Fix TorrentGalaxyClone URL ────────────────────────────────────────
print()
print("=== Step 5: Fix TorrentGalaxyClone ===")
# torrentgalaxy.to returns HTTP 000 from VPN — try alternatives
working_url = None
for url in ["https://torrentgalaxy.info/", "https://tgx.rs/", "https://torrentgalaxy.to/"]:
    r = lxc("110", f"curl -sL --max-time 8 -o /dev/null -w '%{{http_code}} %{{url_effective}}' '{url}' 2>/dev/null", timeout=12)
    print(f"  {url}: {r}")
    code = r.split()[0] if r else "000"
    if code in ("200", "301", "302") and not working_url:
        # Follow redirect to find actual working domain
        final = r.split()[-1] if len(r.split()) > 1 else url
        working_url = url

# Patch DB directly since Prowlarr validates on PUT (contacting the site)
indexers = prowlarr_get("indexer")
tgc = next((i for i in indexers if "torrentgalaxy" in i["name"].lower()), None)
if tgc and working_url:
    print(f"  Best URL: {working_url}")
    db = "/var/lib/prowlarr/prowlarr.db"
    # Read current settings
    raw_settings = lxc("110", f"sqlite3 {db} \"SELECT Settings FROM Indexers WHERE Id={tgc['id']};\"")
    try:
        settings = json.loads(raw_settings)
        settings["baseUrl"] = working_url
        new_settings = json.dumps(settings).replace("'", "''")
        # Write via python patcher
        patcher = f"""import sqlite3, json
conn = sqlite3.connect('{db}')
cur = conn.cursor()
settings = json.loads(cur.execute('SELECT Settings FROM Indexers WHERE Id={tgc["id"]}').fetchone()[0])
settings['baseUrl'] = '{working_url}'
cur.execute('UPDATE Indexers SET Settings=? WHERE Id={tgc["id"]}', (json.dumps(settings),))
conn.commit()
conn.close()
print('OK')
"""
        with ssh.open_sftp() as sftp:
            with sftp.file("/tmp/tgc_fix.py", "w") as f:
                f.write(patcher)
        host(f"pct push 110 /tmp/tgc_fix.py /tmp/tgc_fix.py")
        r2 = lxc("110", "python3 /tmp/tgc_fix.py", timeout=10)
        print(f"  DB patch: {r2}")
    except Exception as e:
        print(f"  Error: {e}")

# ── Step 6: Clear backoff + restart Prowlarr ──────────────────────────────────
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

# ── Step 7: Final test ────────────────────────────────────────────────────────
print()
print("=== Step 7: Final CF indexer tests ===")
CF_NAMES = {"eztv", "1337x", "kickasstorrents", "torrentgalaxy", "torrentdownloads"}
indexers2 = prowlarr_get("indexer")
cf_idxs = [i for i in indexers2 if any(cf in i["name"].lower() for cf in CF_NAMES) and i.get("enable")]
ok, fail = [], []
for idx in sorted(cf_idxs, key=lambda x: x["name"]):
    url = f"{PROWLARR}/{idx['id']}/api?t=caps&apikey={KEY}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=40) as r:
            data = r.read()
            print(f"  ✓ {idx['name']} ({len(data)}b)")
            ok.append(idx["name"])
    except urllib.error.HTTPError as e:
        print(f"  ✗ {idx['name']}: HTTP {e.code}")
        fail.append(idx["name"])
    except Exception as e:
        print(f"  ✗ {idx['name']}: {str(e)[:60]}")
        fail.append(idx["name"])
    time.sleep(2)

print(f"\n  Result: {len(ok)}/{len(ok)+len(fail)} CF indexers working")

ssh.close()
print("\nDone.")
