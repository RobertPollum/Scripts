"""
Dig into specific Windsurf storage keys that may contain conversation data.
"""
import sqlite3
import os
import glob
import json
import re

APPDATA = os.environ["APPDATA"]

def read_key(db_path, key):
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute('SELECT value FROM "ItemTable" WHERE key = ?', (key,))
        row = cur.fetchone()
        con.close()
        return row[0] if row else None
    except Exception as e:
        return f"ERROR: {e}"

# Global storage
global_db = os.path.join(APPDATA, "Windsurf", "User", "globalStorage", "state.vscdb")

interesting_keys = [
    "chat.ChatSessionStore.index",
    "chat.participantNameRegistry",
    "windsurfAuthStatus",
    "windsurfConfigurations",
]

print("=== GLOBAL STORAGE KEY VALUES ===\n")
for key in interesting_keys:
    val = read_key(global_db, key)
    if val:
        print(f"--- {key} ---")
        try:
            parsed = json.loads(val)
            print(json.dumps(parsed, indent=2)[:3000])
        except Exception:
            print(str(val)[:3000])
        print()

# Check workspaceStorage for ChatSessionStore data (not just index)
print("\n=== WORKSPACE STORAGE - ALL CHAT KEYS WITH VALUES ===\n")
base = os.path.join(APPDATA, "Windsurf", "User", "workspaceStorage")
dbs = glob.glob(os.path.join(base, "*", "state.vscdb"))
for db in dbs:
    try:
        con = sqlite3.connect(db)
        cur = con.cursor()
        cur.execute('SELECT key, value FROM "ItemTable" WHERE key LIKE "%chat%"')
        rows = cur.fetchall()
        if rows:
            ws_id = os.path.basename(os.path.dirname(db))
            print(f"--- workspace {ws_id} ---")
            for key, val in rows:
                print(f"  key: {key}")
                try:
                    parsed = json.loads(val)
                    print(f"  value: {json.dumps(parsed, indent=4)[:500]}")
                except Exception:
                    print(f"  value: {str(val)[:500]}")
                print()
        con.close()
    except Exception as e:
        print(f"  Error {db}: {e}")

# Also look at the language server data directory
print("\n=== LANGUAGE SERVER / EXTENSION DATA ===\n")
ext_dirs = [
    os.path.join(APPDATA, "Windsurf", "User", "globalStorage", "codeium.windsurf"),
    os.path.join(APPDATA, "Windsurf", "User", "globalStorage"),
]
for d in ext_dirs:
    if os.path.exists(d):
        print(f"Contents of {d}:")
        for item in os.listdir(d):
            full = os.path.join(d, item)
            size = os.path.getsize(full) if os.path.isfile(full) else "-"
            print(f"  {item}  (size={size})")
        print()

# Check for any SQLite or JSON files in the codeium extension storage
codeium_storage = os.path.join(APPDATA, "Windsurf", "User", "globalStorage", "codeium.windsurf")
if os.path.exists(codeium_storage):
    for f in glob.glob(os.path.join(codeium_storage, "**", "*"), recursive=True):
        if os.path.isfile(f):
            size = os.path.getsize(f)
            print(f"  {f}  ({size} bytes)")
            if f.endswith(".json") and size < 50000:
                try:
                    with open(f) as fh:
                        print(f"    content: {fh.read()[:500]}")
                except Exception:
                    pass
