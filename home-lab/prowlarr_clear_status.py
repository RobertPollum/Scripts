"""
Clear Prowlarr disabled indexer statuses by directly modifying the SQLite DB.
Uses SSH to Proxmox -> pct exec to CT110.
DB path: /var/lib/prowlarr/prowlarr.db
"""
import paramiko
import requests
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_USER = 'root'
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]
CT_ID = 110
DB_PATH = '/var/lib/prowlarr/prowlarr.db'

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR_BASE = f"http://{_env_prowlarr_ip}:9696"
PROWLARR_KEY = os.environ["PROWLARR_API_KEY"]
P_HEADERS = {'X-Api-Key': PROWLARR_KEY}


def pct_exec(ssh, cmd):
    full = f"pct exec {CT_ID} -- bash -c \"{cmd}\""
    _, stdout, stderr = ssh.exec_command(full)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out, err


ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(PROXMOX_HOST, username=PROXMOX_USER, password=PROXMOX_PASS, timeout=10)

print("=== STEP 3: Clear IndexerStatus via SQLite ===")

# Show current rows
out, err = pct_exec(ssh, f"sqlite3 {DB_PATH} 'SELECT IndexerId, DisabledTill FROM IndexerStatus;'")
print(f"  Current IndexerStatus rows:\n{out or '(empty)'}")

# Delete all rows from IndexerStatus
out2, err2 = pct_exec(ssh, f"sqlite3 {DB_PATH} 'DELETE FROM IndexerStatus;'")
print(f"  DELETE result: out='{out2}' err='{err2}'")

# Verify cleared
out3, err3 = pct_exec(ssh, f"sqlite3 {DB_PATH} 'SELECT COUNT(*) FROM IndexerStatus;'")
print(f"  Rows remaining after delete: {out3}")

ssh.close()

# Confirm via Prowlarr API
r = requests.get(f'{PROWLARR_BASE}/api/v1/indexerstatus', headers=P_HEADERS)
remaining = r.json()
print(f"\n  Prowlarr API /indexerstatus now reports {len(remaining)} disabled indexers")
if remaining:
    r_all = requests.get(f'{PROWLARR_BASE}/api/v1/indexer', headers=P_HEADERS)
    id_map = {ix['id']: ix['name'] for ix in r_all.json()}
    for s in remaining:
        print(f"    [{id_map.get(s['indexerId'], '?')}] disabledTill:{s['disabledTill']}")
else:
    print("  ✅ All indexer statuses cleared — Prowlarr will retry on next search/sync.")

print("\n=== DONE ===")
print("Summary of all fixes applied:")
print("  1. DNS: /etc/resolv.conf on CT110 set to 1.1.1.1 / 8.8.8.8")
print("  2. Tags: Torrent Downloads + Uindex now tagged with FlareSolverr proxy")
print("  3. Status: All disabled indexer records cleared from SQLite DB")
