"""
Fix CF indexers by assigning FlareSolverr proxy.
Since Prowlarr's PUT validates by contacting the site (causing timeouts),
we write a Python script into CT110 that patches the DB directly.
"""
import paramiko, os, time, urllib.request, json
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR = f"http://{_env_prowlarr_ip}:9696"
KEY = os.environ["PROWLARR_API_KEY"]

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

# Step 1: Read current settings from DB to understand structure
print("=== Step 1: Read Settings JSON for CF indexers from DB ===")
db = "/var/lib/prowlarr/prowlarr.db"
raw = lxc("110", f"sqlite3 {db} \"SELECT Id,Name,Settings FROM Indexers;\"")
print(raw[:2000])

# Step 2: Get proxy id from API
print()
print("=== Step 2: FlareSolverr proxy id ===")
proxies = prowlarr_get("indexerProxy")
flare = next((p for p in proxies if "flare" in p.get("implementationName","").lower()), None)
print(f"  FlareSolverr id={flare['id'] if flare else 'NOT FOUND'}")
if not flare:
    ssh.close()
    exit(1)

flare_id = flare["id"]

# Step 3: Write a Python patcher script into CT110
print()
print("=== Step 3: Writing patcher script into CT110 ===")

patcher = f"""import sqlite3, json

db = "{db}"
flare_id = {flare_id}
cf_names = ["1337x", "EZTV", "kickasstorrents", "TorrentGalaxy"]

conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("SELECT Id, Name, Settings FROM Indexers")
rows = cur.fetchall()

for idx_id, name, settings_raw in rows:
    if not any(cf.lower() in name.lower() for cf in cf_names):
        continue
    try:
        s = json.loads(settings_raw) if settings_raw else {{}}
    except Exception as e:
        print(f"  {{name}}: parse error {{e}}")
        continue
    
    old_proxy = s.get("proxyId")
    s["proxyId"] = flare_id
    new_settings = json.dumps(s)
    cur.execute("UPDATE Indexers SET Settings=? WHERE Id=?", (new_settings, idx_id))
    print(f"  {{name}} (id={{idx_id}}): proxyId {{old_proxy}} -> {{flare_id}}")

conn.commit()
conn.close()
print("Done.")
"""

# Write to Proxmox host first then push into CT110
with ssh.open_sftp() as sftp:
    with sftp.file("/tmp/prowlarr_patch.py", "w") as f:
        f.write(patcher)

push = lxc("110", "true")  # dummy to get session
result = ssh.exec_command(f"pct push 110 /tmp/prowlarr_patch.py /tmp/prowlarr_patch.py")[1].read().decode().strip()
print(f"  push: {result or 'OK'}")

# Step 4: Stop Prowlarr (so DB isn't locked), run patcher, restart
print()
print("=== Step 4: Stop Prowlarr, patch DB, restart ===")
print(lxc("110", "systemctl stop prowlarr && echo stopped"))
time.sleep(3)

result = lxc("110", "python3 /tmp/prowlarr_patch.py", timeout=15)
print(f"  Patcher output:\n{result}")

print(lxc("110", "systemctl start prowlarr && echo started"))
print("  Waiting 20s...")
time.sleep(20)

for i in range(8):
    try:
        prowlarr_get("health", timeout=8)
        print(f"  Prowlarr up")
        break
    except:
        time.sleep(4)

# Step 5: Verify via API
print()
print("=== Step 5: Verify proxy assignment via API ===")
indexers = prowlarr_get("indexer")
CF_NAMES = {"eztv", "1337x", "kickasstorrents", "torrentgalaxy"}
for idx in sorted(indexers, key=lambda x: x["name"]):
    if any(cf in idx["name"].lower() for cf in CF_NAMES):
        pid = idx.get("indexerProxyId") or idx.get("proxyId")
        mark = "✓" if pid == flare_id else "✗"
        print(f"  {mark} {idx['name']}: proxyId={pid}")

# Step 6: Test via Torznab caps
print()
print("=== Step 6: Test CF indexers via Torznab (with FlareSolverr) ===")
time.sleep(5)
for idx in indexers:
    if any(cf in idx["name"].lower() for cf in CF_NAMES) and idx.get("enable"):
        test_url = f"{PROWLARR}/{idx['id']}/api?t=caps&apikey={KEY}"
        try:
            req = urllib.request.Request(test_url)
            with urllib.request.urlopen(req, timeout=35) as r:
                data = r.read()
                print(f"  {idx['name']}: OK ({len(data)} bytes) ✓")
        except urllib.request.HTTPError as e:
            print(f"  {idx['name']}: HTTP {e.code}")
        except Exception as e:
            print(f"  {idx['name']}: {type(e).__name__}: {str(e)[:80]}")

ssh.close()
print()
print("Done.")
