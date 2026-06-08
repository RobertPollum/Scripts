import sqlite3
import json
import re
import os
from pathlib import Path

APPDATA = os.environ["APPDATA"]
ws_root = Path(APPDATA) / "Windsurf" / "User" / "workspaceStorage"
gs_db = Path(APPDATA) / "Windsurf" / "User" / "globalStorage" / "state.vscdb"

UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)

all_uuids = set()

dbs = [gs_db] + list(ws_root.glob("*/state.vscdb"))

for db in dbs:
    if not db.exists():
        continue
    con = sqlite3.connect(str(db))
    cur = con.cursor()

    # Check all tables
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]

    for table in tables:
        try:
            cur.execute(f"SELECT * FROM [{table}] LIMIT 5")
            col_names = [d[0] for d in cur.description]
            # If there's a 'value' column, scan for UUIDs in its content
            cur.execute(f"SELECT * FROM [{table}]")
            for row in cur.fetchall():
                for cell in row:
                    if isinstance(cell, str) and len(cell) > 30:
                        found = UUID_RE.findall(cell)
                        if found:
                            # Try to parse as JSON and look for cascade/chat context
                            if any(kw in cell.lower() for kw in ['cascade', 'chat', 'trajectory', 'session', 'conversation']):
                                print(f"\n=== {db.name} / table={table} ===")
                                print(f"  Context snippet: {cell[:400]}")
                                all_uuids.update(found)
        except Exception as e:
            pass
    con.close()

print(f"\n\nTotal UUIDs found in cascade/chat context: {len(all_uuids)}")
for u in sorted(all_uuids):
    print(f"  {u}")
