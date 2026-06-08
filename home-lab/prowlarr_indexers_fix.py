"""
Fix the Settings JSON for CF indexers inserted directly into Prowlarr DB.
Prowlarr's CardigannSettings expects a dict, not a list of field objects.
The correct format matches what Prowlarr itself writes: a JSON object with field names as keys.
"""
import paramiko, os, time, json, requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST  = os.environ["PROXMOX_HOST"]
PROXMOX_PASS  = os.environ["PROXMOX_PASSWORD"]
PROWLARR_VMID = "110"
PROWLARR_IP   = os.environ["PROWLARR_IP"]
PROWLARR_KEY  = os.environ["PROWLARR_API_KEY"]
BASE = f"http://{PROWLARR_IP}:9696/api/v1"
HEADERS = {"X-Api-Key": PROWLARR_KEY, "Content-Type": "application/json"}
DB = "/var/lib/prowlarr/prowlarr.db"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def pct(vmid, cmd, timeout=30):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}", timeout=timeout)
    return out.read().decode().strip(), err.read().decode().strip()

# ── Check what a working indexer's Settings look like in the DB ──────────────
print("=== Sample Settings from working indexer (Nyaa.si) ===")
out, _ = pct(PROWLARR_VMID,
    f'sqlite3 {DB} "SELECT Settings FROM Indexers WHERE Name=\'Nyaa.si\';"')
print(repr(out[:500]))

# ── Get the correct settings format from a working Cardigann indexer via API ──
print("\n=== Getting correct settings format from API ===")
schema = requests.get(f"{BASE}/indexer/schema", headers=HEADERS, timeout=15).json()
schema_by_name = {s.get("name","").lower(): s for s in schema}

# Check the definitionFile field — that's the key for Cardigann
# Look at what Nyaa.si (which works) stores vs what we stored
nyaa_schema = schema_by_name.get("nyaa.si", {})
print(f"Nyaa.si configContract: {nyaa_schema.get('configContract')}")
print(f"Nyaa.si fields sample: {[(f['name'], f.get('value')) for f in nyaa_schema.get('fields',[])[:3]]}")

# The correct Settings format for CardigannSettings is a JSON object like:
# {"definitionFile": "1337x", "baseUrl": null, ...}
# NOT a list

CF_INDEXERS = {
    "1337x":            "1337x",
    "EZTV":             "eztv",
    "kickasstorrents.to": "kickasstorrents-to",
    "TorrentGalaxyClone": "torrentgalaxyclone",
}

print("\n=== Fixing Settings format for CF indexers ===")
# Stop Prowlarr
pct(PROWLARR_VMID, "systemctl stop prowlarr 2>/dev/null; sleep 2")
time.sleep(3)

sql_statements = []
for name, def_file in CF_INDEXERS.items():
    s = schema_by_name.get(name.lower())
    if not s:
        print(f"  ✗ '{name}' not in schema")
        continue

    # Build settings as a flat dict (key=field name, value=field value)
    # This matches CardigannSettings property names
    settings = {}
    for f in s.get("fields", []):
        fname = f.get("name","")
        fval  = f.get("value")
        # Skip info/display-only fields
        if fname.startswith("info_"):
            continue
        settings[fname] = fval

    settings_json = json.dumps(settings)

    def sq(v):
        return str(v).replace("'", "''")

    stmt = f"UPDATE Indexers SET Settings='{sq(settings_json)}' WHERE Name='{sq(name)}';"
    sql_statements.append(stmt)
    print(f"  Queued UPDATE for '{name}': settings keys={list(settings.keys())[:5]}...")

# Push and run SQL
full_sql = "\n".join(sql_statements) + "\n"
sftp = c.open_sftp()
with sftp.open("/tmp/prowlarr_fix.sql", "w") as f:
    f.write(full_sql)
sftp.close()

_, hout, herr = c.exec_command(f"pct push {PROWLARR_VMID} /tmp/prowlarr_fix.sql /tmp/prowlarr_fix.sql")
hout.read(); herr.read()

out2, err2 = pct(PROWLARR_VMID,
    f"sqlite3 {DB} < /tmp/prowlarr_fix.sql && echo DONE || echo FAILED", timeout=15)
print(f"  sqlite3: {out2} {err2}")

# Verify what's stored now
out3, _ = pct(PROWLARR_VMID,
    f'sqlite3 {DB} "SELECT Name, substr(Settings,1,80) FROM Indexers WHERE Name IN (\'1337x\',\'EZTV\',\'kickasstorrents.to\',\'TorrentGalaxyClone\');"')
print(f"\nUpdated Settings (first 80 chars):\n{out3}")

# Restart
print("\n=== Restarting Prowlarr ===")
pct(PROWLARR_VMID, "systemctl start prowlarr 2>/dev/null")
time.sleep(10)

# Verify API
print("\n=== API verification ===")
for attempt in range(6):
    try:
        r = requests.get(f"{BASE}/indexer", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            final = r.json()
            print(f"HTTP 200 — {len(final)} indexers")
            for idx in final:
                if not isinstance(idx, dict): continue
                tags = idx.get("tags", [])
                flare = " [FlareSolverr]" if 1 in tags else ""
                print(f"  {idx['name']:<35} enabled={idx.get('enable')}{flare}")
            break
        else:
            print(f"  Attempt {attempt+1}: HTTP {r.status_code} — {r.text[:150]}")
    except Exception as e:
        print(f"  Attempt {attempt+1}: {e}")
    time.sleep(5)

c.close()
print("\nDone.")
