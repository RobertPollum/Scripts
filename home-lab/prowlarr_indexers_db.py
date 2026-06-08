"""
Add CF-protected indexers to Prowlarr by writing directly to its SQLite DB,
bypassing the connectivity test that happens on API POST.

Indexers to inject:
- 1337x        (CF, tag=flaresolverr)
- EZTV         (CF, tag=flaresolverr)
- kickasstorrents.to (CF, tag=flaresolverr)
- TorrentGalaxyClone (CF, tag=flaresolverr)
"""
import paramiko, os, time, json, requests, tempfile
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]
PROWLARR_VMID = "110"
PROWLARR_IP   = os.environ["PROWLARR_IP"]
PROWLARR_KEY  = os.environ["PROWLARR_API_KEY"]
BASE = f"http://{PROWLARR_IP}:9696/api/v1"
HEADERS = {"X-Api-Key": PROWLARR_KEY, "Content-Type": "application/json"}

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def pct(vmid, cmd, timeout=30):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}", timeout=timeout)
    return out.read().decode().strip(), err.read().decode().strip()

# ── Find Prowlarr DB ──────────────────────────────────────────────────────────
print("=== Finding Prowlarr DB ===")
db_path, _ = pct(PROWLARR_VMID, "find / -name 'prowlarr.db' 2>/dev/null | head -3")
print(f"DB: {db_path}")

if not db_path:
    print("ERROR: Could not find prowlarr.db")
    c.close()
    exit(1)

db_path = db_path.splitlines()[0].strip()

# ── Get schema for CF indexers from API ──────────────────────────────────────
print("\n=== Fetching indexer schemas ===")
schema = requests.get(f"{BASE}/indexer/schema", headers=HEADERS, timeout=15).json()
schema_by_name = {s.get("name","").lower(): s for s in schema}

CF_INDEXERS = ["1337x", "EZTV", "kickasstorrents.to", "TorrentGalaxyClone"]

# ── Check which are already in DB ────────────────────────────────────────────
existing_raw, _ = pct(PROWLARR_VMID,
    f"sqlite3 {db_path} \"SELECT Name FROM Indexers;\" 2>/dev/null")
existing_db = [x.strip().lower() for x in existing_raw.splitlines()]
print(f"Already in DB: {existing_db}")

# ── Build INSERT statements ───────────────────────────────────────────────────
# First get the flaresolverr tag id from API
tags = requests.get(f"{BASE}/tag", headers=HEADERS, timeout=10).json()
flare_tag_id = next((t["id"] for t in tags if "flaresolverr" in t.get("label","").lower()), 1)
print(f"FlareSolverr tag id: {flare_tag_id}")

# Get existing indexers to find next available ID
existing_ids, _ = pct(PROWLARR_VMID,
    f"sqlite3 {db_path} \"SELECT Id FROM Indexers ORDER BY Id DESC LIMIT 1;\" 2>/dev/null")
next_id = int(existing_ids.strip() or "0") + 1

# Stop Prowlarr before modifying DB
print("\n=== Stopping Prowlarr service ===")
pct(PROWLARR_VMID, "systemctl stop prowlarr 2>/dev/null; sleep 2")
time.sleep(3)

added = []

# Build a single .sql file with all inserts and push it to the container
sql_statements = []

for indexer_name in CF_INDEXERS:
    s = schema_by_name.get(indexer_name.lower())
    if not s:
        print(f"  ✗ '{indexer_name}' not in schema")
        continue
    if indexer_name.lower() in existing_db:
        print(f"  ⏭  '{indexer_name}' already in DB")
        continue

    # Build the Settings JSON — only include fields with actual values or known defaults
    fields = s.get("fields", [])
    settings_fields = []
    for f in fields:
        val = f.get("value")
        # Skip info/help text fields (they're read-only display fields)
        if f.get("name", "").startswith("info_"):
            continue
        settings_fields.append({"name": f["name"], "value": val})

    settings_json = json.dumps(settings_fields)  # raw JSON, no shell escaping
    tags_json = json.dumps([flare_tag_id])
    impl = s.get("implementation", "")
    config = s.get("configContract", "")

    # SQLite uses '' to escape single quotes inside strings
    def sq(v):
        return str(v).replace("'", "''")

    stmt = (
        f"INSERT INTO Indexers "
        f"(Name, Implementation, Settings, ConfigContract, Enable, Priority, "
        f"AppProfileId, Tags, Added, Redirect, DownloadClientId) VALUES ("
        f"'{sq(indexer_name)}', '{sq(impl)}', '{sq(settings_json)}', '{sq(config)}', "
        f"1, 25, 1, '{sq(tags_json)}', datetime('now'), 0, 0);"
    )
    sql_statements.append(stmt)
    added.append(indexer_name)
    print(f"  Queued: '{indexer_name}'")

if sql_statements:
    full_sql = "\n".join(sql_statements) + "\n"
    # Write SQL file to Proxmox host then push into container
    sftp = c.open_sftp()
    with sftp.open("/tmp/prowlarr_insert.sql", "w") as f:
        f.write(full_sql)
    sftp.close()

    _, hout, herr = c.exec_command(f"pct push {PROWLARR_VMID} /tmp/prowlarr_insert.sql /tmp/prowlarr_insert.sql")
    hout.read(); herr.read()

    out, err = pct(PROWLARR_VMID,
        f"sqlite3 {db_path} < /tmp/prowlarr_insert.sql && echo DONE || echo FAILED",
        timeout=15)
    print(f"  sqlite3 result: {out} {err}")
else:
    print("  Nothing to insert")

# ── Restart Prowlarr ──────────────────────────────────────────────────────────
print("\n=== Restarting Prowlarr ===")
pct(PROWLARR_VMID, "systemctl start prowlarr 2>/dev/null")
time.sleep(8)

# ── Verify via API ────────────────────────────────────────────────────────────
print("\n=== Verifying indexers via API ===")
for attempt in range(5):
    try:
        final = requests.get(f"{BASE}/indexer", headers=HEADERS, timeout=10).json()
        break
    except Exception:
        time.sleep(3)

for idx in final:
    if not isinstance(idx, dict):
        continue
    tags_on = idx.get("tags", [])
    if isinstance(tags_on, str):
        try:
            tags_on = json.loads(tags_on)
        except Exception:
            tags_on = []
    flare = " [FlareSolverr]" if flare_tag_id in tags_on else ""
    print(f"  {idx.get('name'):<35} enabled={idx.get('enable')}{flare}")

c.close()
print(f"\nDone. Added: {added}")
