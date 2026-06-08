"""Inspect Prowlarr DB schema to find where proxy assignments are stored."""
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def lxc(vmid, cmd, timeout=20):
    _, out, _ = ssh.exec_command(f"pct exec {vmid} -- {cmd}", timeout=timeout)
    return out.read().decode(errors="replace").strip()

db = "/var/lib/prowlarr/prowlarr.db"

# Full schema of all tables
print("=== All tables ===")
tables = lxc("110", f"sqlite3 {db} \".tables\"")
print(tables)

print()
print("=== Indexers full schema ===")
print(lxc("110", f"sqlite3 {db} \".schema Indexers\""))

print()
print("=== IndexerProxies full schema ===")
print(lxc("110", f"sqlite3 {db} \".schema IndexerProxies\"") or "(table not found)")

print()
print("=== All tables containing 'proxy' (case-insensitive) ===")
for t in tables.split():
    if "proxy" in t.lower():
        print(f"\n  Table: {t}")
        print(lxc("110", f"sqlite3 {db} \".schema {t}\""))
        print(lxc("110", f"sqlite3 {db} \"SELECT * FROM {t} LIMIT 5;\""))

# Look at full row for a CF indexer to see all columns
print()
print("=== Full row for 1337x (id=10) ===")
print(lxc("110", f"sqlite3 {db} \"SELECT * FROM Indexers WHERE Id=10;\""))

# Try pragma to get column names
print()
print("=== Indexers column names ===")
print(lxc("110", f"sqlite3 {db} \"PRAGMA table_info(Indexers);\""))

# Check if there's an IndexerProxy join table
print()
print("=== Any table with both Indexer and Proxy references ===")
for t in tables.split():
    schema = lxc("110", f"sqlite3 {db} \".schema {t}\"")
    if "index" in schema.lower() and "proxy" in schema.lower():
        print(f"\n  {t}:")
        print(schema)
        print(lxc("110", f"sqlite3 {db} \"SELECT * FROM {t} LIMIT 10;\""))

ssh.close()
