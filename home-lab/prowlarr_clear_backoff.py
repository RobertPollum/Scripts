"""Clear Prowlarr indexer backoff table directly via SQLite, then resync."""
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
    stderr = err.read().decode().strip()
    c.close()
    return result or stderr

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
        return None, f"{e.code}: {e.read().decode()[:200]}"

# Step 1: Find Prowlarr DB
print("=== Step 1: Find Prowlarr database ===")
db_path = ssh_run("110", "find /var/lib /opt /home -name 'prowlarr.db' 2>/dev/null | head -3")
if not db_path:
    db_path = ssh_run("110", "find / -maxdepth 8 -name 'prowlarr.db' 2>/dev/null | grep -v proc | head -3")
print(f"  DB path: {db_path}")

if not db_path:
    print("ERROR: Could not find prowlarr.db")
    exit(1)

# Step 2: Show current backoff entries
print()
print("=== Step 2: Current IndexerStatus backoff entries ===")
result = ssh_run("110", f"sqlite3 {db_path} 'SELECT Id, IndexerId, DisabledTill FROM IndexerStatus WHERE DisabledTill IS NOT NULL;'")
print(f"  {result or '(none)'}")

# Step 3: Clear all backoff entries
print()
print("=== Step 3: Clearing IndexerStatus backoff ===")
result = ssh_run("110", f"sqlite3 {db_path} 'DELETE FROM IndexerStatus; SELECT changes() || \" rows deleted\";'")
print(f"  {result}")

# Also clear from Radarr and Sonarr DBs
for vmid, name, db_name in [("107", "Radarr", "radarr.db"), ("111", "Sonarr", "sonarr.db")]:
    db = ssh_run(vmid, f"find /var/lib /opt -name '{db_name}' 2>/dev/null | head -1")
    if db:
        r = ssh_run(vmid, f"sqlite3 {db} 'DELETE FROM IndexerStatus; SELECT changes() || \" rows deleted\";'")
        print(f"  {name} ({db}): {r}")
    else:
        print(f"  {name}: DB not found")

# Step 4: Restart Prowlarr to pick up cleared state
print()
print("=== Step 4: Restarting Prowlarr + Radarr + Sonarr ===")
for vmid, svc in [("110", "prowlarr"), ("107", "radarr"), ("111", "sonarr")]:
    r = ssh_run(vmid, f"systemctl restart {svc} && echo OK")
    print(f"  {svc}: {r}")

print("  Waiting 25s...")
time.sleep(25)

for label, base, key in [("Prowlarr", PROWLARR, PROWLARR_KEY), ("Radarr", RADARR, RADARR_KEY), ("Sonarr", SONARR, SONARR_KEY)]:
    for i in range(8):
        try:
            path = "/api/v1/health" if "9696" in base else "/api/v3/health"
            get(base, key, path)
            print(f"  {label} up")
            break
        except:
            time.sleep(4)

# Step 5: Check Prowlarr backoff is clear
print()
print("=== Step 5: Prowlarr indexer backoff after clear ===")
statuses = get(PROWLARR, PROWLARR_KEY, "/api/v1/indexerstatus")
if statuses:
    for s in statuses:
        print(f"  indexerId={s.get('indexerId')} disabledTill={s.get('disabledTill')}")
else:
    print("  No backoff entries ✓")

# Step 6: Force sync to Radarr + Sonarr
print()
print("=== Step 6: Force sync Prowlarr -> Radarr + Sonarr ===")
for app_id, name in [(1, "Radarr"), (2, "Sonarr")]:
    r, err = post(PROWLARR, PROWLARR_KEY, "/api/v1/command",
                  {"name": "ApplicationIndexerSync", "applicationId": app_id, "forceSync": True})
    print(f"  {name}: {'id=' + str(r.get('id')) if r else 'ERR: ' + str(err)}")

time.sleep(15)

# Step 7: Final health check
print()
print("=== Step 7: Final health ===")
for label, base, key in [("Prowlarr", PROWLARR, PROWLARR_KEY), ("Radarr", RADARR, RADARR_KEY), ("Sonarr", SONARR, SONARR_KEY)]:
    path = "/api/v1/health" if "9696" in base else "/api/v3/health"
    health = get(base, key, path)
    idx_issues = [h for h in health if "indexer" in h["message"].lower()]
    if idx_issues:
        for h in idx_issues[:1]:
            print(f"  {label} [{h['type']}] {h['message'][:90]}")
    else:
        print(f"  {label}: clean ✓")

# Step 8: Trigger missing searches
print()
print("=== Step 8: Trigger missing searches ===")
movies = get(RADARR, RADARR_KEY, "/api/v3/movie?monitored=true")
missing_ids = [m["id"] for m in movies if not m["hasFile"] and m.get("monitored")]
print(f"  {len(missing_ids)} missing monitored movies")
if missing_ids:
    r, err = post(RADARR, RADARR_KEY, "/api/v3/command", {"name": "MoviesSearch", "movieIds": missing_ids})
    print(f"  Radarr search: {'id=' + str(r.get('id')) if r else 'ERR: ' + str(err)}")

r, err = post(SONARR, SONARR_KEY, "/api/v3/command", {"name": "MissingEpisodeSearch"})
print(f"  Sonarr MissingEpisodeSearch: {'id=' + str(r.get('id')) if r else 'ERR: ' + str(err)}")

print()
print("Done.")
