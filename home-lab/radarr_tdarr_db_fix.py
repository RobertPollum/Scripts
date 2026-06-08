"""
Find and update Jellyfin IP in Radarr (107) and Tdarr (108) SQLite DBs
and config files.
"""
import paramiko
import os
import base64
import sqlite3
import tempfile
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

HOST = os.environ["PROXMOX_HOST"]
USER = os.environ["PROXMOX_USER"].split("@")[0]
PASS = os.environ["PROXMOX_PASSWORD"]

OLD_IP = os.environ["PROWLARR_IP"]
NEW_IP = os.environ["JELLYFIN_IP"]


def get_client():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=10)
    return c


def lxc_run(client, lxc_id, cmd):
    _, stdout, stderr = client.exec_command(
        f"pct exec {lxc_id} -- bash -c " + repr(cmd)
    )
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    return out, err


def find_and_update(client, lxc_id, name):
    print(f"\n{'='*50}")
    print(f"=== {name} (LXC {lxc_id}) ===")
    print(f"{'='*50}")

    # Find all .db files (excluding system dirs)
    out, _ = lxc_run(client, lxc_id,
        "find /var /opt /root /config /home -name '*.db' 2>/dev/null | grep -v apt | grep -v dpkg")
    db_files = [f.strip() for f in out.splitlines() if f.strip()]
    print(f"DB files found: {db_files}")

    # Search for old IP in each DB using sqlite3 CLI
    for db_path in db_files:
        out2, _ = lxc_run(client, lxc_id,
            f"sqlite3 {repr(db_path)} \"SELECT name FROM sqlite_master WHERE type='table';\" 2>/dev/null")
        tables = [t.strip() for t in out2.splitlines() if t.strip()]
        for table in tables:
            out3, _ = lxc_run(client, lxc_id,
                f"sqlite3 {repr(db_path)} \"SELECT * FROM {table} WHERE CAST(\" || chr(34) || \"*\" || chr(34) || \" AS TEXT) LIKE '%{OLD_IP}%';\" 2>/dev/null")
            # Simpler: just grep strings output
        # Use strings to find old IP reference
        out4, _ = lxc_run(client, lxc_id,
            f"strings {repr(db_path)} 2>/dev/null | grep {repr(OLD_IP)}")
        if out4.strip():
            print(f"  FOUND {OLD_IP} in {db_path}:")
            print(f"  {out4.strip()[:500]}")

            # Use sqlite3 to do the update - search all text columns
            out5, _ = lxc_run(client, lxc_id,
                f"sqlite3 {repr(db_path)} \"SELECT name FROM sqlite_master WHERE type='table';\"")
            tables = [t.strip() for t in out5.splitlines() if t.strip()]
            for table in tables:
                # Get columns
                out6, _ = lxc_run(client, lxc_id,
                    f"sqlite3 {repr(db_path)} \"PRAGMA table_info({table});\"")
                cols = []
                for row in out6.splitlines():
                    parts = row.split("|")
                    if len(parts) >= 3 and parts[2].upper() in ("TEXT", "VARCHAR", ""):
                        cols.append(parts[1])
                for col in cols:
                    update_sql = (
                        f"UPDATE {table} SET {col} = REPLACE({col}, '{OLD_IP}', '{NEW_IP}') "
                        f"WHERE {col} LIKE '%{OLD_IP}%';"
                    )
                    out7, err7 = lxc_run(client, lxc_id,
                        f"sqlite3 {repr(db_path)} {repr(update_sql)}")
                    if err7:
                        pass  # silent - most cols won't match
            print(f"  Update applied to {db_path}")
        else:
            print(f"  No {OLD_IP} reference in {db_path}")

    # Also check text/xml config files
    out8, _ = lxc_run(client, lxc_id,
        f"grep -rl '{OLD_IP}' /var /opt /root /config /home 2>/dev/null "
        f"| grep -v apt | grep -v dpkg | grep -v '\\.db$' | head -20")
    conf_files = [f.strip() for f in out8.splitlines() if f.strip()]
    if conf_files:
        print(f"\nText config files with {OLD_IP}: {conf_files}")
        for filepath in conf_files:
            content, err = lxc_run(client, lxc_id, f"cat {repr(filepath)}")
            if not content:
                continue
            updated = content.replace(OLD_IP, NEW_IP)
            b64 = base64.b64encode(updated.encode()).decode()
            _, werr = lxc_run(client, lxc_id, f"echo {b64} | base64 -d > {repr(filepath)}")
            if werr:
                print(f"  [write err] {werr}")
            else:
                print(f"  Updated {filepath}")
    else:
        print(f"\nNo text config files referencing {OLD_IP}")

    # Restart service
    out9, _ = lxc_run(client, lxc_id,
        "systemctl list-units --all --type=service | grep -E 'radarr|tdarr' | awk '{print $1}'")
    services = [s.strip() for s in out9.splitlines() if s.strip()]
    if services:
        for svc in services:
            print(f"\nRestarting {svc}...")
            lxc_run(client, lxc_id, f"systemctl restart {svc}")
            status, _ = lxc_run(client, lxc_id, f"systemctl is-active {svc}")
            print(f"  {svc}: {status.strip()}")
    else:
        print("\nNo service found to restart.")


client = get_client()
print(f"Connected to Proxmox {HOST}")
print(f"Updating Jellyfin IP: {OLD_IP} -> {NEW_IP}")

find_and_update(client, "107", "Radarr")
find_and_update(client, "108", "Tdarr")

client.close()
print("\n=== All done ===")
