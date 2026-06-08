"""Restart Prowlarr to clear indexer backoff, then re-test all indexers, then sync to Radarr/Sonarr."""
import paramiko, os, time, urllib.request, json, urllib.error
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

def ssh_run(vmid, cmd):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c '{cmd}'")
    result = out.read().decode().strip()
    c.close()
    return result

def get(base, key, path):
    req = urllib.request.Request(base + path, headers={"X-Api-Key": key})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def post(base, key, path, data=None):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(base + path, data=body,
                                  headers={"X-Api-Key": key, "Content-Type": "application/json"})
    req.get_method = lambda: "POST"
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"{e.code}: {e.read().decode()[:300]}"

# Step 1: Restart Prowlarr (CT110)
print("=== Step 1: Restarting Prowlarr (CT110) ===")
print(ssh_run("110", "systemctl restart prowlarr && echo OK"))
print("  Waiting 20s...")
time.sleep(20)

for i in range(12):
    try:
        get(PROWLARR, PROWLARR_KEY, "/api/v1/health")
        print(f"  Prowlarr up (attempt {i+1})")
        break
    except Exception as e:
        print(f"  Not ready (attempt {i+1}): {e}")
        time.sleep(5)

# Step 2: Check Prowlarr health after restart
print()
print("=== Step 2: Prowlarr health after restart ===")
health = get(PROWLARR, PROWLARR_KEY, "/api/v1/health")
if health:
    for h in health:
        print(f"  [{h['type']}] {h['message'][:100]}")
else:
    print("  No health issues ✓")

# Step 3: Check indexer status (backoff)
print()
print("=== Step 3: Indexer backoff status ===")
statuses = get(PROWLARR, PROWLARR_KEY, "/api/v1/indexerstatus")
if statuses:
    for s in statuses:
        print(f"  indexerId={s.get('indexerId')} disabledTill={s.get('disabledTill','?')}")
else:
    print("  No indexers in backoff ✓")

# Step 4: Test each enabled indexer
print()
print("=== Step 4: Testing all enabled indexers ===")
indexers = get(PROWLARR, PROWLARR_KEY, "/api/v1/indexer")
enabled = [i for i in indexers if i.get("enable", True)]
print(f"  {len(enabled)} enabled indexers")

for idx in enabled:
    name = idx["name"]
    idx_id = idx["id"]
    # Quick caps test via Torznab
    fields = {f["name"]: f.get("value") for f in idx.get("fields", []) if "value" in f}
    base_url = fields.get("baseUrl", "")
    if base_url:
        test_url = base_url.rstrip("/") + f"/api?t=caps&apikey={PROWLARR_KEY}"
        try:
            req = urllib.request.Request(test_url)
            with urllib.request.urlopen(req, timeout=10) as r:
                r.read()
            print(f"  {name} (id={idx_id}): OK")
        except Exception as e:
            print(f"  {name} (id={idx_id}): FAIL - {str(e)[:80]}")
    else:
        print(f"  {name} (id={idx_id}): no baseUrl")

# Step 5: Force sync to Radarr and Sonarr
print()
print("=== Step 5: Force sync Prowlarr -> Radarr + Sonarr ===")
time.sleep(3)
for app_id, name in [(1, "Radarr"), (2, "Sonarr")]:
    r, err = post(PROWLARR, PROWLARR_KEY, "/api/v1/command",
                  {"name": "ApplicationIndexerSync", "applicationId": app_id, "forceSync": True})
    print(f"  {name}: {'queued id=' + str(r.get('id')) if r else 'ERROR: ' + str(err)}")

print("  Waiting 20s...")
time.sleep(20)

# Step 6: Final indexer counts + health
print()
print("=== Step 6: Final state ===")
for label, base, key in [("Radarr", RADARR, RADARR_KEY), ("Sonarr", SONARR, SONARR_KEY)]:
    idxs = get(base, key, "/api/v3/indexer")
    health = get(base, key, "/api/v3/health")
    idx_errors = [h for h in health if "indexer" in h["message"].lower()]
    print(f"  {label}: {len(idxs)} indexers | health issues: {len(idx_errors)}")
    if idx_errors:
        for h in idx_errors[:2]:
            print(f"    [{h['type']}] {h['message'][:80]}")

# Step 7: Trigger missing searches on both
print()
print("=== Step 7: Trigger missing searches ===")
r, err = post(RADARR, RADARR_KEY, "/api/v3/command",
              {"name": "MissingMoviesSearch", "filterKey": "monitored", "filterValue": "true"})
print(f"  Radarr MissingMoviesSearch: {'id=' + str(r.get('id')) if r else 'ERR: ' + str(err)}")

# If bulk fails, individual
if err:
    movies = get(RADARR, RADARR_KEY, "/api/v3/movie?monitored=true")
    missing_ids = [m["id"] for m in movies if not m["hasFile"] and m.get("monitored")]
    r2, err2 = post(RADARR, RADARR_KEY, "/api/v3/command",
                    {"name": "MoviesSearch", "movieIds": missing_ids})
    print(f"  Radarr bulk MoviesSearch ({len(missing_ids)} movies): {'id=' + str(r2.get('id')) if r2 else 'ERR: ' + str(err2)}")

r, err = post(SONARR, SONARR_KEY, "/api/v3/command", {"name": "MissingEpisodeSearch"})
print(f"  Sonarr MissingEpisodeSearch: {'id=' + str(r.get('id')) if r else 'ERR: ' + str(err)}")

print()
print("Done. Check Radarr/Sonarr Activity > Queue in a few minutes.")
