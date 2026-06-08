"""Clear indexer backoff by piping SQL directly via stdin to sqlite3 inside the LXC."""
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

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def run(cmd, stdin_data=None):
    chan = ssh.get_transport().open_session()
    chan.exec_command(cmd)
    if stdin_data:
        chan.sendall(stdin_data.encode())
        chan.shutdown_write()
    stdout = chan.makefile("r").read().strip()
    stderr = chan.makefile_stderr("r").read().strip()
    chan.close()
    return stdout or stderr

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

# Step 1: Clear backoff by piping SQL to sqlite3 via stdin
print("=== Step 1: Clearing IndexerStatus via sqlite3 stdin ===")
for vmid, db_path, name in [
    ("110", "/var/lib/prowlarr/prowlarr.db", "Prowlarr"),
    ("107", "/var/lib/radarr/radarr.db", "Radarr"),
    ("111", "/var/lib/sonarr/sonarr.db", "Sonarr"),
]:
    sql = "DELETE FROM IndexerStatus;\n.quit\n"
    result = run(f"pct exec {vmid} -- sqlite3 {db_path}", stdin_data=sql)
    # Verify
    check = run(f"pct exec {vmid} -- sqlite3 {db_path}", stdin_data="SELECT COUNT(*) FROM IndexerStatus;\n.quit\n")
    print(f"  {name}: cleared. Remaining rows: {check or result or '0'}")

# Step 2: Restart all three
print()
print("=== Step 2: Restarting services ===")
for vmid, svc in [("110", "prowlarr"), ("107", "radarr"), ("111", "sonarr")]:
    run(f"pct exec {vmid} -- systemctl restart {svc}")
    print(f"  {svc}: restarted")

print("  Waiting 25s...")
time.sleep(25)

for label, base, key in [
    ("Prowlarr", PROWLARR, PROWLARR_KEY),
    ("Radarr", RADARR, RADARR_KEY),
    ("Sonarr", SONARR, SONARR_KEY),
]:
    path = "/api/v1/health" if "9696" in base else "/api/v3/health"
    for i in range(10):
        try:
            get(base, key, path)
            print(f"  {label} up")
            break
        except:
            time.sleep(4)

# Step 3: Verify backoff gone
print()
print("=== Step 3: Prowlarr backoff check ===")
statuses = get(PROWLARR, PROWLARR_KEY, "/api/v1/indexerstatus")
if not statuses:
    print("  No backoff entries ✓")
else:
    for s in statuses:
        print(f"  indexerId={s.get('indexerId')} disabledTill={s.get('disabledTill')}")

# Step 4: Force sync
print()
print("=== Step 4: Force sync ===")
time.sleep(5)
for app_id, name in [(1, "Radarr"), (2, "Sonarr")]:
    r, err = post(PROWLARR, PROWLARR_KEY, "/api/v1/command",
                  {"name": "ApplicationIndexerSync", "applicationId": app_id, "forceSync": True})
    print(f"  {name}: {'id=' + str(r.get('id')) if r else 'ERR: ' + str(err)}")

print("  Waiting 20s...")
time.sleep(20)

# Step 5: Health
print()
print("=== Step 5: Final health ===")
for label, base, key in [
    ("Prowlarr", PROWLARR, PROWLARR_KEY),
    ("Radarr", RADARR, RADARR_KEY),
    ("Sonarr", SONARR, SONARR_KEY),
]:
    path = "/api/v1/health" if "9696" in base else "/api/v3/health"
    health = get(base, key, path)
    idx_issues = [h for h in health if "indexer" in h["message"].lower()]
    if not idx_issues:
        print(f"  {label}: clean ✓")
    else:
        for h in idx_issues[:1]:
            print(f"  {label} [{h['type']}] {h['message'][:90]}")

# Step 6: Trigger searches
print()
print("=== Step 6: Trigger missing searches ===")
movies = get(RADARR, RADARR_KEY, "/api/v3/movie?monitored=true")
missing_ids = [m["id"] for m in movies if not m["hasFile"] and m.get("monitored")]
print(f"  {len(missing_ids)} missing monitored movies")
if missing_ids:
    r, err = post(RADARR, RADARR_KEY, "/api/v3/command", {"name": "MoviesSearch", "movieIds": missing_ids})
    print(f"  Radarr: {'id=' + str(r.get('id')) if r else 'ERR: ' + str(err)}")

r, err = post(SONARR, SONARR_KEY, "/api/v3/command", {"name": "MissingEpisodeSearch"})
print(f"  Sonarr: {'id=' + str(r.get('id')) if r else 'ERR: ' + str(err)}")

ssh.close()
print()
print("Done.")
