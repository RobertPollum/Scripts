import sqlite3
import json
import os
import re
from pathlib import Path

APPDATA = os.environ["APPDATA"]
gs_db = Path(APPDATA) / "Windsurf" / "User" / "globalStorage" / "state.vscdb"

con = sqlite3.connect(str(gs_db))
cur = con.cursor()

# Dump all keys + first 300 chars of value to find auth tokens
cur.execute("SELECT key, value FROM ItemTable")
for key, value in cur.fetchall():
    if not value:
        continue
    if any(k in key.lower() for k in ('auth', 'token', 'codeium', 'windsurf_auth', 'secret', 'session', 'api')):
        print(f"\nKey: {key}")
        try:
            parsed = json.loads(value)
            print(json.dumps(parsed, indent=2)[:600])
        except:
            print(repr(value[:600]))

con.close()

# Also check secrets stored separately
print("\n\n--- Checking secret:// entries ---")
con = sqlite3.connect(str(gs_db))
cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'secret://%'")
for key, value in cur.fetchall():
    print(f"\nKey: {key}")
    try:
        parsed = json.loads(value)
        print(json.dumps(parsed, indent=2)[:600])
    except:
        print(repr(value[:600]))
con.close()
