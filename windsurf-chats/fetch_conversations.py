"""
fetch_conversations.py

Uses the Windsurf/Codeium API key stored locally to fetch the full
conversation list from server.self-serve.windsurf.com, then writes
all discovered UUIDs into index.json for export.

Run:
  python fetch_conversations.py           -- fetch and update index
  python fetch_conversations.py --dump    -- print raw API response
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
INDEX_FILE = SCRIPT_DIR / "index.json"
APPDATA = os.environ["APPDATA"]
GS_DB = Path(APPDATA) / "Windsurf" / "User" / "globalStorage" / "state.vscdb"

# ---------------------------------------------------------------------------
# Read auth from local Windsurf DB
# ---------------------------------------------------------------------------

def get_auth() -> tuple[str, str]:
    """Return (api_key, api_server_url) from globalStorage state.vscdb."""
    con = sqlite3.connect(str(GS_DB))
    cur = con.cursor()

    cur.execute("SELECT value FROM ItemTable WHERE key = 'windsurfAuthStatus'")
    row = cur.fetchone()
    if not row:
        sys.exit("ERROR: windsurfAuthStatus not found in DB. Is Windsurf installed and logged in?")
    auth = json.loads(row[0])
    api_key = auth.get("apiKey")

    cur.execute("SELECT value FROM ItemTable WHERE key = 'codeium.windsurf'")
    row = cur.fetchone()
    conf = json.loads(row[0]) if row else {}
    api_url = conf.get("apiServerUrl", "https://server.self-serve.windsurf.com").rstrip("/")

    con.close()
    return api_key, api_url


# ---------------------------------------------------------------------------
# API probing
# ---------------------------------------------------------------------------

CANDIDATE_PATHS = [
    "/api/v1/conversations",
    "/api/v1/cascade/conversations",
    "/api/v1/chat/conversations",
    "/api/v1/trajectories",
    "/api/v2/conversations",
    "/api/v1/user/conversations",
    "/cascade/v1/conversations",
    "/v1/conversations",
]

def probe_endpoints(api_key: str, api_url: str) -> None:
    """Try candidate endpoints and print responses."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    for path in CANDIDATE_PATHS:
        url = api_url + path
        try:
            r = requests.get(url, headers=headers, timeout=10)
            print(f"{r.status_code}  GET {url}")
            if r.status_code == 200:
                print("  ", r.text[:500])
        except Exception as e:
            print(f"ERR  GET {url}  — {e}")


def fetch_conversations_grpc_json(api_key: str, api_url: str, dump: bool = False) -> list[dict]:
    """
    Try the GetCascadeConversations gRPC-JSON endpoint pattern used by Codeium.
    Returns list of conversation dicts with at minimum {id, title, created_at}.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "x-codeium-api-key": api_key,
    }

    # Codeium uses Connect/gRPC-JSON protocol
    grpc_candidates = [
        f"{api_url}/exa.assistant_pb.AssistantService/GetConversations",
        f"{api_url}/exa.chat_pb.ChatService/GetConversations",
        f"{api_url}/exa.aichat_pb.AIChatService/GetConversations",
        f"{api_url}/exa.cascade_pb.CascadeService/GetConversations",
        f"{api_url}/exa.cascade_pb.CascadeService/ListConversations",
        f"{api_url}/exa.windsurf_pb.WindsurfService/GetConversations",
        f"{api_url}/exa.windsurf_pb.WindsurfService/ListConversations",
        f"{api_url}/exa.trajectory_pb.TrajectoryService/ListTrajectories",
        f"{api_url}/exa.trajectory_pb.TrajectoryService/GetTrajectories",
        # Also try REST-style
        f"{api_url}/api/v1/conversations",
        f"{api_url}/api/v2/conversations",
        f"{api_url}/api/v1/cascade/sessions",
        f"{api_url}/api/v1/sessions",
    ]

    results = []
    for url in grpc_candidates:
        try:
            # POST with empty body (gRPC-JSON convention)
            r = requests.post(url, headers=headers, json={}, timeout=10)
            status = r.status_code
            snippet = r.text[:300].replace('\n', ' ')
            print(f"  POST {status}  {url}")
            if status == 200 and r.text.strip():
                print(f"    >> {snippet}")
                if dump:
                    print(r.text[:2000])
                results.append({"url": url, "body": r.text})
            # Also try GET
            r2 = requests.get(url, headers=headers, timeout=10)
            status2 = r2.status_code
            if status2 == 200 and r2.text.strip():
                print(f"  GET  {status2}  {url}")
                print(f"    >> {r2.text[:300].replace(chr(10), ' ')}")
                results.append({"url": url + " (GET)", "body": r2.text})
        except Exception as e:
            print(f"  ERR  {url}  — {e}")

    return results


# ---------------------------------------------------------------------------
# Index helpers (same as export_windsurf_chats.py)
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text).strip("-")
    return text[:60]


def load_index() -> dict:
    if INDEX_FILE.exists():
        with open(INDEX_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"conversations": {}, "last_updated": None}


def save_index(index: dict) -> None:
    index["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
    print(f"Index saved → {INDEX_FILE}")


def update_index_from_conversations(convos: list[dict]) -> None:
    index = load_index()
    new_count = 0
    for c in convos:
        uuid = c.get("id") or c.get("uuid") or c.get("conversation_id")
        if not uuid:
            continue
        if uuid not in index["conversations"]:
            index["conversations"][uuid] = {
                "uuid": uuid,
                "title": c.get("title") or c.get("name") or "Untitled",
                "category": "cascade",
                "created_at": c.get("created_at") or c.get("createdAt"),
                "exported": False,
                "export_path": None,
            }
            new_count += 1
    save_index(index)
    total = len(index["conversations"])
    pending = sum(1 for v in index["conversations"].values() if not v["exported"])
    print(f"Index: {total} total, {pending} pending, {new_count} newly added.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", action="store_true", help="Print full API responses")
    args = parser.parse_args()

    api_key, api_url = get_auth()
    print(f"API server: {api_url}")
    print(f"API key:    {api_key[:20]}...")
    print()

    print("=== Probing endpoints ===")
    results = fetch_conversations_grpc_json(api_key, api_url, dump=args.dump)

    if not results:
        print("\nNo 200 responses found. Trying broader probe...")
        probe_endpoints(api_key, api_url)
    else:
        print(f"\n{len(results)} successful endpoint(s) found.")
        for r in results:
            print(f"  {r['url']}")
            try:
                parsed = json.loads(r["body"])
                # Look for a list of conversations
                for key in ("conversations", "sessions", "items", "data", "trajectories"):
                    if key in parsed and isinstance(parsed[key], list):
                        print(f"  Found {len(parsed[key])} items under '{key}'")
                        update_index_from_conversations(parsed[key])
                        break
                else:
                    if isinstance(parsed, list):
                        print(f"  Response is a list of {len(parsed)} items")
                        update_index_from_conversations(parsed)
            except:
                pass


if __name__ == "__main__":
    main()
