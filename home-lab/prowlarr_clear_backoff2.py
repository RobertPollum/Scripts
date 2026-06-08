"""Clear indexer backoff by writing a shell script to the LXC and executing it."""
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

def get_ssh():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)
    return c

def run_host(cmd):
    c = get_ssh()
    _, out, err = c.exec_command(cmd)
    result = out.read().decode().strip()
    stderr = err.read().decode().strip()
    c.close()
    return result or stderr

def write_and_run(vmid, script_content, script_path="/tmp/_fix.sh"):
    """Write a script into the LXC via Proxmox and run it."""
    c = get_ssh()
    sftp_proxy = c.get_transport().open_session()
    # Write script to Proxmox host first, then push into LXC
    host_path = f"/tmp/lxc_{vmid}_fix.sh"
    with c.open_sftp() as sftp:
        with sftp.file(host_path, "w") as f:
            f.write(script_content)
    # Copy into LXC
    run1_cmd = f"pct push {vmid} {host_path} {script_path} && chmod +x {script_path}"
    _, out, err = c.exec_command(run1_cmd)
    out.read(); err.read()
    # Execute inside LXC
    _, out, err = c.exec_command(f"pct exec {vmid} -- {script_path}")
    result = out.read().decode().strip()
    stderr = err.read().decode().strip()
    # Cleanup
    c.exec_command(f"rm -f {host_path}")
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

# Step 1: Clear backoff in Prowlarr, Radarr, Sonarr DBs
print("=== Step 1: Clearing IndexerStatus backoff via SQLite ===")

for vmid, db_path, name in [
    ("110", "/var/lib/prowlarr/prowlarr.db", "Prowlarr"),
    ("107", "/var/lib/radarr/radarr.db", "Radarr"),
    ("111", "/var/lib/sonarr/sonarr.db", "Sonarr"),
]:
    script = f"""#!/bin/bash
sqlite3 {db_path} "DELETE FROM IndexerStatus;"
echo "{name}: cleared $(sqlite3 {db_path} 'SELECT COUNT(*) FROM IndexerStatus;') remaining rows"
"""
    result = write_and_run(vmid, script)
    print(f"  {result}")

# Step 2: Restart all three services
print()
print("=== Step 2: Restarting Prowlarr, Radarr, Sonarr ===")
for vmid, svc in [("110", "prowlarr"), ("107", "radarr"), ("111", "sonarr")]:
    result = run_host(f"pct exec {vmid} -- systemctl restart {svc}")
    print(f"  {svc}: restarted")

print("  Waiting 25s...")
time.sleep(25)

# Wait for all to come up
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

# Step 3: Check backoff is gone
print()
print("=== Step 3: Prowlarr backoff after clear ===")
statuses = get(PROWLARR, PROWLARR_KEY, "/api/v1/indexerstatus")
if not statuses:
    print("  No backoff entries ✓")
else:
    for s in statuses:
        print(f"  indexerId={s.get('indexerId')} disabledTill={s.get('disabledTill')}")

# Step 4: Force sync to Radarr + Sonarr
print()
print("=== Step 4: Force sync Prowlarr -> Radarr + Sonarr ===")
time.sleep(5)
for app_id, name in [(1, "Radarr"), (2, "Sonarr")]:
    r, err = post(PROWLARR, PROWLARR_KEY, "/api/v1/command",
                  {"name": "ApplicationIndexerSync", "applicationId": app_id, "forceSync": True})
    print(f"  {name}: {'id=' + str(r.get('id')) if r else 'ERR: ' + str(err)}")

print("  Waiting 20s...")
time.sleep(20)

# Step 5: Final health + trigger searches
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

print()
print("=== Step 6: Trigger missing searches ===")
movies = get(RADARR, RADARR_KEY, "/api/v3/movie?monitored=true")
missing_ids = [m["id"] for m in movies if not m["hasFile"] and m.get("monitored")]
print(f"  {len(missing_ids)} missing monitored movies")
if missing_ids:
    r, err = post(RADARR, RADARR_KEY, "/api/v3/command", {"name": "MoviesSearch", "movieIds": missing_ids})
    print(f"  Radarr search: {'id=' + str(r.get('id')) if r else 'ERR: ' + str(err)}")

r, err = post(SONARR, SONARR_KEY, "/api/v3/command", {"name": "MissingEpisodeSearch"})
print(f"  Sonarr: {'id=' + str(r.get('id')) if r else 'ERR: ' + str(err)}")

print()
print("Done.")
