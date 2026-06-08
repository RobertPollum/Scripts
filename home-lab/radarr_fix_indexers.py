"""Fix Radarr indexer failures: restart to clear backoff, force sync, trigger missing search."""
import urllib.request, json, time, urllib.error
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]
_env_radarr_ip = os.environ["RADARR_IP"]
RADARR = f"http://{_env_radarr_ip}:7878"
RADARR_KEY = os.environ["RADARR_API_KEY"]
_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR = f"http://{_env_prowlarr_ip}:9696"
PROWLARR_KEY = os.environ["PROWLARR_API_KEY"]

def ssh_run(vmid, cmd):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c '{cmd}'")
    result = out.read().decode().strip()
    c.close()
    return result

def radarr_get(path):
    req = urllib.request.Request(RADARR + "/api/v3/" + path, headers={"X-Api-Key": RADARR_KEY})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def radarr_post(path, data=None):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(RADARR + "/api/v3/" + path, data=body,
                                  headers={"X-Api-Key": RADARR_KEY, "Content-Type": "application/json"})
    req.get_method = lambda: "POST"
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def prowlarr_post(path, data=None):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, data=body,
                                  headers={"X-Api-Key": PROWLARR_KEY, "Content-Type": "application/json"})
    req.get_method = lambda: "POST"
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

# Step 1: Restart Radarr (CT107) to clear indexer backoff cache
print("=== STEP 1: Restarting Radarr (CT107) ===")
out = ssh_run("107", "systemctl restart radarr && echo OK")
print("  Result:", out)
print("  Waiting 15s for Radarr to come back up...")
time.sleep(15)

for attempt in range(10):
    try:
        radarr_get("system/status")
        print(f"  Radarr is up (attempt {attempt+1})")
        break
    except Exception:
        print(f"  Not ready (attempt {attempt+1})...")
        time.sleep(5)

# Step 2: Force sync Prowlarr -> Radarr (Radarr app id=1)
print()
print("=== STEP 2: Force syncing Prowlarr -> Radarr ===")
r = prowlarr_post("command", {"name": "ApplicationIndexerSync", "applicationId": 1, "forceSync": True})
print(f"  Sync queued: id={r.get('id')}")
time.sleep(12)

# Step 3: Report indexers + health
print()
print("=== STEP 3: Radarr indexers after sync ===")
idxs = radarr_get("indexer")
print(f"  Count: {len(idxs)}")
for i in idxs:
    print(f"  {i['name']}")

print()
print("=== STEP 4: Radarr health ===")
for h in radarr_get("health"):
    print(f"  [{h['type']}] {h['message'][:100]}")

# Step 5: Trigger RSS + missing movie search
print()
print("=== STEP 5: Triggering RSS Sync + Missing Movies Search ===")
r = radarr_post("command", {"name": "RssSync"})
print(f"  RssSync queued: id={r.get('id')}")

try:
    r = radarr_post("command", {"name": "MissingMoviesSearch", "filterKey": "monitored", "filterValue": "true"})
    print(f"  MissingMoviesSearch queued: id={r.get('id')}")
except urllib.error.HTTPError as e:
    err = e.read().decode()
    print(f"  MissingMoviesSearch error: {e.code} {err[:200]}")
    # Fallback: search each missing movie individually
    print("  Trying per-movie search fallback...")
    movies = radarr_get("movie?monitored=true")
    missing = [mv for mv in movies if not mv["hasFile"] and mv.get("monitored")]
    print(f"  Found {len(missing)} missing monitored movies")
    for mv in missing:
        try:
            r2 = radarr_post("command", {"name": "MoviesSearch", "movieIds": [mv["id"]]})
            print(f"    Queued search for: {mv['title']} ({mv.get('year')}) id={r2.get('id')}")
        except Exception as e2:
            print(f"    Failed for {mv['title']}: {e2}")

print()
print("Done. Check Radarr Activity > Queue in a few minutes.")
