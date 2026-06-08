import sqlite3
import json
import re
import os
from pathlib import Path

APPDATA = os.environ["APPDATA"]
ws_root = Path(APPDATA) / "Windsurf" / "User" / "workspaceStorage"
gs_db = Path(APPDATA) / "Windsurf" / "User" / "globalStorage" / "state.vscdb"

dbs = [gs_db] + list(ws_root.glob("*/state.vscdb"))

for db in dbs:
    if not db.exists():
        continue
    con = sqlite3.connect(str(db))
    cur = con.cursor()
    cur.execute("SELECT key, value FROM ItemTable")
    for key, value in cur.fetchall():
        if not value:
            continue
        # Look specifically for keys that sound like cascade/chat session storage
        if any(k in key.lower() for k in ('cascade', 'chat', 'session', 'conversation', 'windsurf')):
            print(f"\n{'='*60}")
            print(f"DB: {db.parent.name}/{db.name}")
            print(f"Key: {key}")
            try:
                parsed = json.loads(value)
                print(json.dumps(parsed, indent=2)[:2000])
            except:
                print(repr(value[:1000]))
    con.close()
