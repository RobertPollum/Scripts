"""
Probe Windsurf local storage for conversation/chat data.
Checks workspaceStorage SQLite DBs and Session Storage for UUID patterns.
"""
import sqlite3
import os
import glob
import re
import json

APPDATA = os.environ["APPDATA"]

# 1. workspaceStorage SQLite DBs
print("=" * 60)
print("WORKSPACE STORAGE SQLite DBs")
print("=" * 60)

base = os.path.join(APPDATA, "Windsurf", "User", "workspaceStorage")
dbs = glob.glob(os.path.join(base, "*", "state.vscdb"))
for db in dbs:
    try:
        con = sqlite3.connect(db)
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        print(f"\n--- {os.path.basename(os.path.dirname(db))} ---")
        print(f"Tables: {tables}")
        for t in tables:
            cur.execute(
                f'SELECT key, length(value) FROM "{t}" '
                f'WHERE key LIKE "%cascade%" OR key LIKE "%chat%" '
                f'OR key LIKE "%conversation%" OR key LIKE "%trajectory%" '
                f'OR key LIKE "%windsurf%" LIMIT 20'
            )
            rows = cur.fetchall()
            if rows:
                print(f"  [{t}] chat-related keys:")
                for key, vlen in rows:
                    print(f"    {key}  (value len={vlen})")
        con.close()
    except Exception as e:
        print(f"  Error: {e}")

# 2. globalStorage
print("\n" + "=" * 60)
print("GLOBAL STORAGE SQLite DB")
print("=" * 60)
global_db = os.path.join(APPDATA, "Windsurf", "User", "globalStorage", "state.vscdb")
if os.path.exists(global_db):
    try:
        con = sqlite3.connect(global_db)
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        print(f"Tables: {tables}")
        for t in tables:
            cur.execute(
                f'SELECT key, length(value) FROM "{t}" '
                f'WHERE key LIKE "%cascade%" OR key LIKE "%chat%" '
                f'OR key LIKE "%conversation%" OR key LIKE "%trajectory%" '
                f'OR key LIKE "%windsurf%" OR key LIKE "%history%" LIMIT 30'
            )
            rows = cur.fetchall()
            if rows:
                print(f"  [{t}] chat-related keys:")
                for key, vlen in rows:
                    print(f"    {key}  (value len={vlen})")
        con.close()
    except Exception as e:
        print(f"  Error: {e}")
else:
    print(f"Not found: {global_db}")

# 3. Scan Session Storage for UUIDs
print("\n" + "=" * 60)
print("SESSION STORAGE (UUID scan)")
print("=" * 60)
session_dir = os.path.join(APPDATA, "Windsurf", "Session Storage")
uuid_pattern = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
found_uuids = set()
if os.path.exists(session_dir):
    for f in glob.glob(os.path.join(session_dir, "**", "*"), recursive=True):
        if os.path.isfile(f):
            try:
                with open(f, "rb") as fh:
                    content = fh.read().decode("utf-8", errors="ignore")
                    uuids = uuid_pattern.findall(content)
                    if uuids:
                        found_uuids.update(uuids)
            except Exception:
                pass
    print(f"Found {len(found_uuids)} unique UUIDs in Session Storage")
    for u in sorted(found_uuids)[:30]:
        print(f"  {u}")
else:
    print("Session Storage dir not found")

# 4. Local Storage leveldb — look for readable text with UUIDs
print("\n" + "=" * 60)
print("LOCAL STORAGE leveldb (UUID scan)")
print("=" * 60)
ls_dir = os.path.join(APPDATA, "Windsurf", "Local Storage", "leveldb")
found_ls_uuids = set()
if os.path.exists(ls_dir):
    for f in glob.glob(os.path.join(ls_dir, "*.ldb")):
        try:
            with open(f, "rb") as fh:
                content = fh.read().decode("utf-8", errors="ignore")
                uuids = uuid_pattern.findall(content)
                found_ls_uuids.update(uuids)
        except Exception:
            pass
    print(f"Found {len(found_ls_uuids)} unique UUIDs in Local Storage leveldb")
    for u in sorted(found_ls_uuids)[:30]:
        print(f"  {u}")
