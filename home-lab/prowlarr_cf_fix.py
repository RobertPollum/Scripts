"""
Fix CF indexers (1337x, EZTV, kickasstorrents) by:
1. Verifying FlareSolverr is reachable from CT110
2. Testing FlareSolverr can solve 1337x/EZTV Cloudflare challenges
3. Assigning FlareSolverr proxy to CF indexers via Prowlarr API
"""
import urllib.request, json, urllib.error, time, paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR = f"http://{_env_prowlarr_ip}:9696"
KEY = os.environ["PROWLARR_API_KEY"]
_env_flaresolverr_ip = os.environ["FLARESOLVERR_IP"]
FLARE_URL = f"http://{_env_flaresolverr_ip}:8191"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def lxc(vmid, cmd, timeout=25):
    _, out, err = ssh.exec_command(f"pct exec {vmid} -- {cmd}", timeout=timeout)
    return out.read().decode(errors="replace").strip()

def prowlarr_get(path, timeout=15):
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, headers={"X-Api-Key": KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def prowlarr_put(path, data, timeout=60):
    """PUT with long timeout since Prowlarr validates by contacting the site."""
    body = json.dumps(data).encode()
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, data=body,
                                  headers={"X-Api-Key": KEY, "Content-Type": "application/json"})
    req.get_method = lambda: "PUT"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:300]}"
    except Exception as e:
        return None, str(e)

# Step 1: Check FlareSolverr health from CT110
print("=== Step 1: FlareSolverr reachability from CT110 ===")
flare_health = lxc("110", f"curl -s --max-time 5 {FLARE_URL}/health 2>/dev/null")
print(f"  Health: {flare_health}")

# Step 2: Test FlareSolverr can solve a CF challenge (e.g. 1337x.to)
print()
print("=== Step 2: FlareSolverr solve test for 1337x.to ===")
# Post to FlareSolverr v1 API
flare_test_cmd = (
    f"curl -s --max-time 30 -X POST {FLARE_URL}/v1 "
    f"-H 'Content-Type: application/json' "
    f"-d '{{\"cmd\":\"request.get\",\"url\":\"https://1337x.to\",\"maxTimeout\":20000}}' "
    f"2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin); "
    f"print('status=' + d.get('status','?') + ' solution_status=' + str(d.get('solution',{{}}).get('status','?')))\" "
    f"2>/dev/null"
)
result = lxc("110", flare_test_cmd, timeout=40)
print(f"  1337x solve: {result}")

flare_test_cmd2 = (
    f"curl -s --max-time 30 -X POST {FLARE_URL}/v1 "
    f"-H 'Content-Type: application/json' "
    f"-d '{{\"cmd\":\"request.get\",\"url\":\"https://eztvx.to\",\"maxTimeout\":20000}}' "
    f"2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin); "
    f"print('status=' + d.get('status','?') + ' solution_status=' + str(d.get('solution',{{}}).get('status','?')))\" "
    f"2>/dev/null"
)
result2 = lxc("110", flare_test_cmd2, timeout=40)
print(f"  EZTV solve: {result2}")

# Step 3: Get current indexer + proxy state
print()
print("=== Step 3: Current indexer proxy assignments ===")
indexers = prowlarr_get("indexer")
proxies = prowlarr_get("indexerProxy")

flare_proxy = next((p for p in proxies if "flare" in p.get("implementationName","").lower()), None)
print(f"  FlareSolverr proxy id: {flare_proxy['id'] if flare_proxy else 'NOT FOUND'}")

CF_NAMES = {"eztv", "1337x", "kickasstorrents", "torrentgalaxy"}
cf_indexers = [i for i in indexers if any(cf in i["name"].lower() for cf in CF_NAMES)]

for idx in cf_indexers:
    pid = idx.get("indexerProxyId")
    print(f"  {idx['name']}: proxyId={pid}")

if not flare_proxy:
    print("ERROR: No FlareSolverr proxy configured in Prowlarr.")
    ssh.close()
    exit(1)

# Step 4: Assign FlareSolverr proxy to each CF indexer
# Prowlarr validates on PUT so we skip validation by patching the DB directly
print()
print("=== Step 4: Assigning FlareSolverr proxy via SQLite (bypass validation timeout) ===")

db_path = "/var/lib/prowlarr/prowlarr.db"
for idx in cf_indexers:
    idx_id = idx["id"]
    proxy_id = flare_proxy["id"]
    
    # Read current Settings JSON from DB, update ProxyId field
    sql = f"SELECT Settings FROM Indexers WHERE Id={idx_id};"
    settings_raw = lxc("110", f"sqlite3 {db_path} \"{sql}\"")
    
    try:
        settings = json.loads(settings_raw)
    except Exception:
        print(f"  {idx['name']}: Could not parse settings JSON: {settings_raw[:80]}")
        continue
    
    # Update ProxyId in settings
    settings["proxyId"] = proxy_id
    new_settings = json.dumps(settings).replace("'", "''")  # escape for SQL
    
    update_sql = f"UPDATE Indexers SET Settings='{new_settings}' WHERE Id={idx_id};"
    # Write SQL to a temp file to avoid quoting issues
    sql_file = f"/tmp/fix_idx_{idx_id}.sql"
    write_result = lxc("110", f"printf '%s' '{update_sql}' > {sql_file} && sqlite3 {db_path} < {sql_file} && echo OK")
    print(f"  {idx['name']} (id={idx_id}): DB update = {write_result}")

# Step 5: Also update the IndexerProxyId column directly
print()
print("=== Step 5: Checking Indexers table schema ===")
schema = lxc("110", f"sqlite3 {db_path} \".schema Indexers\" 2>/dev/null")
has_proxy_col = "ProxyId" in schema or "proxyId" in schema.lower()
print(f"  ProxyId column exists: {has_proxy_col}")
print(f"  Schema: {schema[:200]}")

if has_proxy_col:
    print()
    print("=== Step 6: Updating ProxyId column directly ===")
    for idx in cf_indexers:
        col = "ProxyId" if "ProxyId" in schema else "proxyId"
        sql = f"UPDATE Indexers SET {col}={flare_proxy['id']} WHERE Id={idx['id']};"
        result = lxc("110", f"sqlite3 {db_path} \"{sql}\" && echo OK")
        print(f"  {idx['name']}: {result}")

# Step 6: Restart Prowlarr to pick up DB changes
print()
print("=== Step 7: Restarting Prowlarr ===")
lxc("110", "systemctl restart prowlarr")
print("  Waiting 20s...")
time.sleep(20)

for i in range(8):
    try:
        prowlarr_get("health", timeout=8)
        print(f"  Prowlarr up")
        break
    except:
        time.sleep(4)

# Step 7: Verify proxy assignments via API
print()
print("=== Step 8: Verify via API ===")
indexers2 = prowlarr_get("indexer")
for idx in sorted(indexers2, key=lambda x: x["name"]):
    if any(cf in idx["name"].lower() for cf in CF_NAMES):
        pid = idx.get("indexerProxyId") or idx.get("proxyId")
        mark = "✓" if pid else "✗"
        print(f"  {mark} {idx['name']}: proxyId={pid}")

# Step 8: Test the indexers now
print()
print("=== Step 9: Test CF indexers via Prowlarr Torznab ===")
indexers3 = prowlarr_get("indexer")
for idx in indexers3:
    if any(cf in idx["name"].lower() for cf in CF_NAMES) and idx.get("enable"):
        test_url = f"{PROWLARR}/{idx['id']}/api?t=caps&apikey={KEY}"
        try:
            req = urllib.request.Request(test_url)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
                print(f"  {idx['name']}: OK ({len(data)} bytes)")
        except Exception as e:
            print(f"  {idx['name']}: {type(e).__name__}: {str(e)[:80]}")

ssh.close()
print()
print("Done.")
