"""
Diagnose and fix Sonarr indexer failures.
1. Restart Sonarr to clear backoff cache
2. Verify indexers are healthy
3. Trigger a search for missing episodes
"""
import paramiko, os, time, json, urllib.request, urllib.error
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]
_env_sonarr_ip = os.environ["SONARR_IP"]
SONARR = f"http://{_env_sonarr_ip}:8989"
SONARR_KEY = os.environ["SONARR_API_KEY"]
_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR = f"http://{_env_prowlarr_ip}:9696"
PROWLARR_KEY = os.environ["PROWLARR_API_KEY"]
SONARR_VMID = "111"

def ssh_run(vmid, cmd):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c '{cmd}'")
    result = out.read().decode().strip()
    error = err.read().decode().strip()
    c.close()
    return result, error

def sonarr_get(path):
    req = urllib.request.Request(SONARR + "/api/v3/" + path, headers={"X-Api-Key": SONARR_KEY})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def sonarr_post(path, data=None):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(SONARR + "/api/v3/" + path, data=body,
                                  headers={"X-Api-Key": SONARR_KEY, "Content-Type": "application/json"})
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

# --- Step 1: Check current health ---
print("=== STEP 1: Current Sonarr health ===")
for h in sonarr_get("health"):
    print(f"  [{h['type']}] {h['message']}")

# --- Step 2: Restart Sonarr to clear backoff ---
print()
print("=== STEP 2: Restarting Sonarr (CT111) to clear indexer backoff ===")
out, err = ssh_run(SONARR_VMID, "systemctl restart sonarr && echo OK")
print(f"  Result: {out or err}")

print("  Waiting 15s for Sonarr to come back up...")
time.sleep(15)

# --- Step 3: Wait for Sonarr to respond ---
for attempt in range(10):
    try:
        sonarr_get("system/status")
        print(f"  Sonarr is up (attempt {attempt+1})")
        break
    except Exception:
        print(f"  Not ready yet (attempt {attempt+1})...")
        time.sleep(5)

# --- Step 4: Trigger Prowlarr->Sonarr sync ---
print()
print("=== STEP 3: Triggering Prowlarr indexer sync to Sonarr ===")
try:
    r = prowlarr_post("command", {"name": "ApplicationIndexerSync", "applicationId": 2})
    print(f"  Sync command queued: id={r.get('id')} name={r.get('name')}")
except Exception as e:
    print(f"  Sync error: {e}")

time.sleep(10)

# --- Step 5: Check health again ---
print()
print("=== STEP 4: Health after restart + sync ===")
for h in sonarr_get("health"):
    print(f"  [{h['type']}] {h['message']}")

print()
print("=== STEP 5: Sonarr indexers ===")
idxs = sonarr_get("indexer")
print(f"  Count: {len(idxs)}")
for i in idxs:
    print(f"  id={i['id']} name={i['name']}")

# --- Step 6: Trigger RSS sync + missing search ---
print()
print("=== STEP 6: Triggering RSS Sync + Missing Episode Search ===")
try:
    r = sonarr_post("command", {"name": "RssSync"})
    print(f"  RssSync queued: id={r.get('id')}")
except Exception as e:
    print(f"  RssSync error: {e}")

try:
    r = sonarr_post("command", {"name": "MissingEpisodeSearch"})
    print(f"  MissingEpisodeSearch queued: id={r.get('id')}")
except Exception as e:
    print(f"  MissingEpisodeSearch error: {e}")

print()
print("Done. Check Sonarr Activity > Queue in a few minutes.")
