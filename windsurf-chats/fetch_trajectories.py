"""
fetch_trajectories.py

Fetches all Cascade conversation IDs from the locally running Windsurf
language server and writes them into index.json for export.

How it works:
  1. Finds the running language_server_windows_x64 process via WMI.
  2. Reads --csrf_token and the listening port from its command line args.
  3. Calls GetAllCascadeTrajectories on http://127.0.0.1:{port}/...
  4. Populates index.json with every discovered conversation.

Usage:
  python fetch_trajectories.py           -- fetch and update index.json
  python fetch_trajectories.py --dump    -- also print the raw API response
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
INDEX_FILE = SCRIPT_DIR / "index.json"

LS_BINARY = "language_server_windows_x64"
SERVICE    = "exa.language_server_pb.LanguageServerService"


# ---------------------------------------------------------------------------
# Language server discovery
# ---------------------------------------------------------------------------

def get_ls_info() -> tuple[int, str]:
    """Return (port, csrf_token) from the running language server process."""
    ps = subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            f"Get-CimInstance Win32_Process -Filter \"Name LIKE '%language_server%'\" "
            "| Select-Object -ExpandProperty CommandLine",
        ],
        capture_output=True, text=True, timeout=15,
    )
    cmdlines = ps.stdout.strip().splitlines()

    for line in cmdlines:
        if LS_BINARY not in line:
            continue
        # Extract --csrf_token VALUE
        csrf_m = re.search(r"--csrf_token\s+(\S+)", line)
        # Extract port: language server listens on --random_port; actual port
        # is what's open on 127.0.0.1. We also check extension_server_port
        # but the HTTP/gRPC port is found via netstat below.
        if not csrf_m:
            continue
        csrf_token = csrf_m.group(1)

        # Find the port this process is listening on
        port = _find_ls_port(csrf_token)
        if port:
            return port, csrf_token

    sys.exit(
        "ERROR: Windsurf language server process not found.\n"
        "Make sure Windsurf is running and open a workspace."
    )


def _find_ls_port(csrf_token: str) -> int | None:
    """Find the TCP port the language server HTTP server is listening on.

    The language server process listens on multiple ports (LSP, gRPC/HTTP,
    extension server). We probe each listening port on 127.0.0.1 with the
    CSRF token until we get a non-401/non-connection-error response.
    """
    # Get PID from WMI
    ps = subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            f"Get-CimInstance Win32_Process -Filter \"Name LIKE '%language_server%'\" "
            "| Select-Object ProcessId, CommandLine | ConvertTo-Json",
        ],
        capture_output=True, text=True, timeout=15,
    )
    try:
        procs = json.loads(ps.stdout)
        if isinstance(procs, dict):
            procs = [procs]
    except Exception:
        return None

    pid = None
    for p in procs:
        cl = p.get("CommandLine", "")
        if LS_BINARY in cl and "--csrf_token" in cl:
            pid = p.get("ProcessId")
            break

    if not pid:
        return None

    # Get all listening ports for this PID on 127.0.0.1
    ps2 = subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            f"Get-NetTCPConnection -OwningProcess {pid} -State Listen "
            "-ErrorAction SilentlyContinue | Where-Object {{ $_.LocalAddress -eq '127.0.0.1' }} "
            "| Select-Object -ExpandProperty LocalPort",
        ],
        capture_output=True, text=True, timeout=15,
    )
    ports = sorted(
        [int(x.strip()) for x in ps2.stdout.strip().splitlines() if x.strip().isdigit()]
    )

    # Probe each port — the HTTP/gRPC port responds to our endpoint (200 or 403/401 with JSON)
    for port in ports:
        try:
            r = requests.post(
                f"http://127.0.0.1:{port}/{SERVICE}/GetAllCascadeTrajectories",
                headers={"Content-Type": "application/json", "x-codeium-csrf-token": csrf_token},
                json={},
                timeout=5,
            )
            # Any HTTP response (even 4xx) means this is the HTTP port
            if r.status_code == 200:
                return port
            # 401/403 with JSON body = correct port but auth issue
            if r.status_code in (401, 403) and r.headers.get("Content-Type", "").startswith("application/json"):
                return port
        except requests.exceptions.ConnectionError:
            continue  # Not an HTTP port (e.g. LSP uses a different protocol)
        except Exception:
            continue

    return None


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def fetch_all_trajectories(port: int, csrf_token: str, dump: bool = False) -> dict:
    url = f"http://127.0.0.1:{port}/{SERVICE}/GetAllCascadeTrajectories"
    headers = {
        "Content-Type": "application/json",
        "x-codeium-csrf-token": csrf_token,
    }
    r = requests.post(url, headers=headers, json={}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if dump:
        print(json.dumps(data, indent=2))
    return data


# ---------------------------------------------------------------------------
# Index helpers
# ---------------------------------------------------------------------------

def load_index() -> dict:
    if INDEX_FILE.exists():
        with open(INDEX_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"conversations": {}, "last_updated": None}


def save_index(index: dict) -> None:
    index["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
    print(f"Index saved -> {INDEX_FILE}")


def update_index(data: dict) -> tuple[int, int]:
    """Parse API response and upsert conversations into index.json.
    Returns (total, new_count).
    """
    index = load_index()
    new_count = 0

    # Response shape: {"trajectorySummaries": {"<key_id>": {trajectoryId, summary, ...}}}
    summaries: dict = data.get("trajectorySummaries", {})

    for outer_key, item in summaries.items():
        # trajectory_search requires the OUTER key (not the inner trajectoryId field)
        uuid = outer_key
        if not uuid:
            continue

        title = item.get("summary") or item.get("title") or item.get("name") or "Untitled"
        created_at = item.get("createdTime") or item.get("created_at")
        step_count = item.get("stepCount", 0)
        workspace = ""
        ws_list = item.get("workspaces", [])
        if ws_list:
            repo = ws_list[0].get("repository", {})
            workspace = repo.get("computedName", "") or ws_list[0].get("workspaceFolderAbsoluteUri", "")

        if uuid not in index["conversations"]:
            index["conversations"][uuid] = {
                "uuid": uuid,
                "trajectory_id": item.get("trajectoryId", ""),
                "title": title,
                "category": "cascade",
                "step_count": step_count,
                "workspace": workspace,
                "created_at": created_at,
                "exported": False,
                "export_path": None,
            }
            new_count += 1
        else:
            # Refresh mutable metadata
            index["conversations"][uuid]["title"] = title
            index["conversations"][uuid]["step_count"] = step_count
            index["conversations"][uuid]["trajectory_id"] = item.get("trajectoryId", "")

    save_index(index)
    return len(index["conversations"]), new_count


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch all Windsurf Cascade conversations into index.json")
    parser.add_argument("--dump", action="store_true", help="Print the raw API response")
    args = parser.parse_args()

    print("Locating Windsurf language server...")
    port, csrf_token = get_ls_info()
    print(f"  Port       : {port}")
    print(f"  CSRF token : {csrf_token[:12]}...")
    print()

    print("Calling GetAllCascadeTrajectories...")
    data = fetch_all_trajectories(port, csrf_token, dump=args.dump)

    total, new_count = update_index(data)
    pending = sum(
        1 for v in load_index()["conversations"].values() if not v["exported"]
    )
    print(f"\nDone.  Total: {total}  |  New: {new_count}  |  Pending export: {pending}")


if __name__ == "__main__":
    main()
