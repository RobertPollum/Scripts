"""
Check CF indexer backoff, clear it, and do a proper end-to-end test
through Prowlarr's own indexer test endpoint (not Torznab caps).
"""
import urllib.request, json, urllib.error, time, paramiko, os
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

def get(path, timeout=15):
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, headers={"X-Api-Key": KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def post(path, data=None, timeout=60):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, data=body,
                                  headers={"X-Api-Key": KEY, "Content-Type": "application/json"})
    req.get_method = lambda: "POST"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}"), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:300]}"
    except Exception as e:
        return None, str(e)

CF_NAMES = {"eztv", "1337x", "kickasstorrents", "torrentgalaxy"}

# Step 1: Check current backoff
print("=== Step 1: Current backoff status ===")
statuses = get("indexerstatus")
indexers = get("indexer")
cf_idxs = [i for i in indexers if any(cf in i["name"].lower() for cf in CF_NAMES)]

for idx in cf_idxs:
    bs = next((s for s in statuses if s.get("indexerId") == idx["id"]), None)
    if bs:
        print(f"  {idx['name']}: BACKOFF until {bs.get('disabledTill','?')[:19]}")
    else:
        print(f"  {idx['name']}: no backoff")

# Step 2: Clear backoff from DB
print()
print("=== Step 2: Clear IndexerStatus backoff ===")
db = "/var/lib/prowlarr/prowlarr.db"
result = lxc("110", f"sqlite3 {db} \"DELETE FROM IndexerStatus;\" && echo cleared")
print(f"  {result}")

# Step 3: Restart Prowlarr to flush in-memory backoff
print()
print("=== Step 3: Restart Prowlarr ===")
lxc("110", "systemctl restart prowlarr")
print("  Waiting 20s...")
time.sleep(20)
for i in range(8):
    try:
        get("health", timeout=8)
        print("  Prowlarr up")
        break
    except:
        time.sleep(4)

# Step 4: Verify FlareSolverr is up from CT110
print()
print("=== Step 4: FlareSolverr health ===")
flare_health = lxc("110", f"curl -s --max-time 5 http://{os.environ['FLARESOLVERR_IP']}:8191/health 2>/dev/null")
print(f"  {flare_health}")

# Step 5: Use Prowlarr's own /api/v1/indexer/{id}/test endpoint
print()
print("=== Step 5: Prowlarr indexer test (official endpoint) ===")
indexers2 = get("indexer")
cf_idxs2 = [i for i in indexers2 if any(cf in i["name"].lower() for cf in CF_NAMES) and i.get("enable")]

for idx in cf_idxs2:
    print(f"  Testing {idx['name']} (id={idx['id']})...", end=" ", flush=True)
    result, err = post(f"indexer/test", {"id": idx["id"]}, timeout=60)
    if err:
        print(f"FAIL: {err[:100]}")
    else:
        print(f"OK")
    time.sleep(3)  # avoid hammering

# Step 6: Check health after tests
print()
print("=== Step 6: Prowlarr health after tests ===")
health = get("health")
for h in health:
    print(f"  [{h['type']}] {h['message'][:100]}")
if not health:
    print("  Clean ✓")

# Step 7: Check backoff again
print()
print("=== Step 7: Backoff after tests ===")
statuses2 = get("indexerstatus")
cf_back = [s for s in statuses2 if any(
    cf in next((i["name"] for i in indexers2 if i["id"] == s.get("indexerId")), "").lower()
    for cf in CF_NAMES
)]
if not cf_back:
    print("  No CF indexers in backoff ✓")
else:
    for s in cf_back:
        name = next((i["name"] for i in indexers2 if i["id"] == s.get("indexerId")), "?")
        print(f"  {name}: disabledTill={s.get('disabledTill','?')[:19]}")

ssh.close()
