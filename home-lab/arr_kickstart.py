"""
After Prowlarr network fix: clear indexer backoff, sync all apps, trigger missing searches.
"""
import urllib.request, json, time, urllib.error
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR = f"http://{_env_prowlarr_ip}:9696"
PROWLARR_KEY = os.environ["PROWLARR_API_KEY"]
_env_radarr_ip = os.environ["RADARR_IP"]
RADARR = f"http://{_env_radarr_ip}:7878"
RADARR_KEY = os.environ["RADARR_API_KEY"]
_env_sonarr_ip = os.environ["SONARR_IP"]
SONARR = f"http://{_env_sonarr_ip}:8989"
SONARR_KEY = os.environ["SONARR_API_KEY"]

def get(base, key, path):
    req = urllib.request.Request(base + path, headers={"X-Api-Key": key})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def post(base, key, path, data=None):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(base + path, data=body,
                                  headers={"X-Api-Key": key, "Content-Type": "application/json"})
    req.get_method = lambda: "POST"
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"{e.code}: {e.read().decode()[:200]}"

def ssh_run(vmid, cmd):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c '{cmd}'")
    result = out.read().decode().strip()
    c.close()
    return result

# Step 1: Verify Prowlarr is reachable and test indexers
print("=== Step 1: Prowlarr indexer health ===")
try:
    health = get(PROWLARR, PROWLARR_KEY, "/api/v1/health")
    if health:
        for h in health:
            print(f"  [{h['type']}] {h['message']}")
    else:
        print("  No health issues")
except Exception as e:
    print(f"  Prowlarr unreachable: {e}")
    exit(1)

# Step 2: Restart Radarr to clear its 6h+ indexer backoff
print()
print("=== Step 2: Restarting Radarr to clear indexer backoff ===")
print(ssh_run("107", "systemctl restart radarr && echo OK"))
print("  Waiting 15s...")
time.sleep(15)
for i in range(8):
    try:
        get(RADARR, RADARR_KEY, "/api/v3/system/status")
        print(f"  Radarr up (attempt {i+1})")
        break
    except:
        time.sleep(5)

# Step 3: Force sync Prowlarr -> all apps
print()
print("=== Step 3: Force sync Prowlarr -> Radarr + Sonarr ===")
for app_id, name in [(1, "Radarr"), (2, "Sonarr")]:
    r, err = post(PROWLARR, PROWLARR_KEY, "/api/v1/command",
                  {"name": "ApplicationIndexerSync", "applicationId": app_id, "forceSync": True})
    if err:
        print(f"  {name} sync error: {err}")
    else:
        print(f"  {name} sync queued: id={r.get('id')}")

print("  Waiting 15s for sync...")
time.sleep(15)

# Step 4: Check indexer counts
print()
print("=== Step 4: Indexer counts after sync ===")
radarr_idxs = get(RADARR, RADARR_KEY, "/api/v3/indexer")
sonarr_idxs = get(SONARR, SONARR_KEY, "/api/v3/indexer")
print(f"  Radarr: {len(radarr_idxs)} indexers: {[i['name'] for i in radarr_idxs]}")
print(f"  Sonarr: {len(sonarr_idxs)} indexers: {[i['name'] for i in sonarr_idxs]}")

# Step 5: Health check
print()
print("=== Step 5: Health ===")
for label, base, key in [("Radarr", RADARR, RADARR_KEY), ("Sonarr", SONARR, SONARR_KEY)]:
    issues = get(base, key, "/api/v3/health")
    indexer_issues = [h for h in issues if "indexer" in h["message"].lower()]
    if indexer_issues:
        for h in indexer_issues:
            print(f"  {label} [{h['type']}] {h['message'][:100]}")
    else:
        print(f"  {label}: No indexer health issues ✓")

# Step 6: Trigger missing searches
print()
print("=== Step 6: Trigger missing movie + episode searches ===")
r, err = post(RADARR, RADARR_KEY, "/api/v3/command", {"name": "MissingMoviesSearch", "filterKey": "monitored", "filterValue": "true"})
if err:
    # Fallback: search each movie individually
    movies = get(RADARR, RADARR_KEY, "/api/v3/movie?monitored=true")
    missing = [m for m in movies if not m["hasFile"] and m.get("monitored")]
    print(f"  MissingMoviesSearch fallback: searching {len(missing)} movies individually")
    for mv in missing:
        r2, _ = post(RADARR, RADARR_KEY, "/api/v3/command", {"name": "MoviesSearch", "movieIds": [mv["id"]]})
        print(f"    {mv['title']} ({mv.get('year')}) -> id={r2.get('id') if r2 else 'ERR'}")
else:
    print(f"  Radarr MissingMoviesSearch queued: id={r.get('id')}")

r, err = post(SONARR, SONARR_KEY, "/api/v3/command", {"name": "MissingEpisodeSearch"})
if err:
    print(f"  Sonarr MissingEpisodeSearch error: {err}")
else:
    print(f"  Sonarr MissingEpisodeSearch queued: id={r.get('id')}")

# Step 7: Check queue in 30s
print()
print("Waiting 30s then checking queues...")
time.sleep(30)

radarr_q = get(RADARR, RADARR_KEY, "/api/v3/queue?pageSize=5")
sonarr_q = get(SONARR, SONARR_KEY, "/api/v3/queue?pageSize=5")
print(f"  Radarr queue: {radarr_q['totalRecords']} items")
print(f"  Sonarr queue: {sonarr_q['totalRecords']} items")
for item in radarr_q.get("records", []):
    print(f"    {item['title'][:60]} | {item['status']}")

print()
print("Done.")
