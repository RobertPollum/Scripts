"""
Try to find the correct Codeium/Windsurf API server for conversation history
by checking all URLs referenced in the local DB and trying known Codeium endpoints.
"""
import sqlite3
import json
import os
import re
import requests
from pathlib import Path

APPDATA = os.environ["APPDATA"]
GS_DB = Path(APPDATA) / "Windsurf" / "User" / "globalStorage" / "state.vscdb"

# Extract all URLs from DB
con = sqlite3.connect(str(GS_DB))
cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable")
rows = cur.fetchall()
con.close()

URL_RE = re.compile(r'https?://[a-zA-Z0-9._/-]+')
urls = set()
for key, value in rows:
    if value and isinstance(value, str):
        found = URL_RE.findall(value)
        for u in found:
            # Filter out CDN/telemetry noise, keep codeium/windsurf
            if any(x in u for x in ('codeium', 'windsurf', 'server')):
                urls.add(u.rstrip('/'))

print("URLs referencing codeium/windsurf/server found in DB:")
for u in sorted(urls):
    print(f"  {u}")

# Get the API key
con = sqlite3.connect(str(GS_DB))
cur = con.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key = 'windsurfAuthStatus'")
row = cur.fetchone()
auth = json.loads(row[0])
api_key = auth["apiKey"]
con.close()

print(f"\nAPI key: {api_key[:30]}...")

# Try the known Codeium server.codeium.com which is the trajectory host
# The trajectory_search tool uses a different backend than self-serve
CODEIUM_SERVERS = [
    "https://server.codeium.com",
    "https://api.codeium.com",
    "https://web-backend.codeium.com",
    "https://server.self-serve.windsurf.com",
]

TRAJECTORY_PATHS = [
    "/exa.language_server_pb.LanguageServerService/GetConversations",
    "/exa.language_server_pb.LanguageServerService/ListConversations",
    "/exa.agentic_ux_pb.AgenticUXService/GetConversations",
    "/exa.agentic_ux_pb.AgenticUXService/ListConversations",
    "/exa.agentic_ux_pb.AgenticUXService/GetTrajectories",
    "/exa.agentic_ux_pb.AgenticUXService/ListTrajectories",
    "/exa.agentic_ux_pb.AgenticUXService/GetCascadeConversations",
    "/exa.cascade_ux_pb.CascadeUXService/ListConversations",
    "/exa.cascade_ux_pb.CascadeUXService/GetConversations",
    "/exa.copilot_pb.CopilotService/GetConversations",
    "/api/v1/conversations",
    "/api/v1/trajectories",
]

headers = {
    "Authorization": f"Bearer {api_key}",
    "x-codeium-api-key": api_key,
    "Content-Type": "application/json",
}

print("\n=== Probing servers + paths ===")
for server in CODEIUM_SERVERS:
    for path in TRAJECTORY_PATHS:
        url = server + path
        try:
            r = requests.post(url, headers=headers, json={}, timeout=8)
            if r.status_code != 404:
                print(f"  [{r.status_code}] POST {url}")
                if r.status_code == 200:
                    print(f"    BODY: {r.text[:400]}")
        except Exception as e:
            pass  # Suppress connection errors for speed
