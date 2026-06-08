"""
watcher.py

Polls the Windsurf language server every 60 seconds, detects conversations
that have been modified since last export, and writes/updates Obsidian notes.

Replaces the broken post_cascade_response_with_transcript hook which stopped
firing after Windsurf moved from JSONL transcripts to protobuf storage.

Run once at login via Task Scheduler:
  python watcher.py

Or run manually:
  python watcher.py              # poll loop (default 60s interval)
  python watcher.py --once       # single pass, then exit
  python watcher.py --interval 30
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCRIPT_DIR   = Path(__file__).parent
INDEX_FILE   = SCRIPT_DIR / "index.json"
LOG_FILE     = SCRIPT_DIR / "watcher.log"


def _load_dotenv() -> dict[str, str]:
    """Load key=value pairs from .env in the script directory."""
    env: dict[str, str] = {}
    env_path = SCRIPT_DIR / ".env"
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    env[key.strip()] = val.strip()
    return env


_DOTENV = _load_dotenv()
_vault_path = _DOTENV.get("OBSIDIAN_VAULT_PATH") or os.environ.get("OBSIDIAN_VAULT")
if not _vault_path:
    raise SystemExit(
        "ERROR: OBSIDIAN_VAULT_PATH not set in .env or OBSIDIAN_VAULT environment variable.\n"
        "Create a .env file in the script directory with:\n"
        '  OBSIDIAN_VAULT_PATH=C:\\\\Users\\\\YOUR_NAME\\\\...\\\\Your-Vault'
    )
VAULT_CHATS_DIR = Path(_vault_path) / "Chats"

LS_BINARY = "language_server_windows_x64"
SERVICE   = "exa.language_server_pb.LanguageServerService"

POLL_INTERVAL = 60  # seconds

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("watcher")

# ---------------------------------------------------------------------------
# Language server discovery (same logic as fetch_trajectories.py)
# ---------------------------------------------------------------------------

def get_ls_info() -> tuple[int, str] | None:
    """Return (port, csrf_token) or None if LS is not running."""
    try:
        ps = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Get-CimInstance Win32_Process -Filter \"Name LIKE '%language_server%'\" "
                "| Select-Object -ExpandProperty CommandLine",
            ],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as e:
        log.warning(f"WMI query failed: {e}")
        return None

    for line in ps.stdout.strip().splitlines():
        if LS_BINARY not in line:
            continue
        csrf_m = re.search(r"--csrf_token\s+(\S+)", line)
        if not csrf_m:
            continue
        csrf_token = csrf_m.group(1)
        port = _find_ls_port(csrf_token)
        if port:
            return port, csrf_token

    return None


def _find_ls_port(csrf_token: str) -> int | None:
    try:
        ps = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Get-CimInstance Win32_Process -Filter \"Name LIKE '%language_server%'\" "
                "| Select-Object ProcessId, CommandLine | ConvertTo-Json",
            ],
            capture_output=True, text=True, timeout=15,
        )
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

    try:
        ps2 = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Get-NetTCPConnection -OwningProcess {pid} -State Listen "
                "-ErrorAction SilentlyContinue | Where-Object {{ $_.LocalAddress -eq '127.0.0.1' }} "
                "| Select-Object -ExpandProperty LocalPort",
            ],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return None

    ports = sorted(
        [int(x.strip()) for x in ps2.stdout.strip().splitlines() if x.strip().isdigit()]
    )
    for port in ports:
        try:
            r = requests.post(
                f"http://127.0.0.1:{port}/{SERVICE}/GetAllCascadeTrajectories",
                headers={"Content-Type": "application/json", "x-codeium-csrf-token": csrf_token},
                json={},
                timeout=5,
            )
            if r.status_code == 200:
                return port
            if r.status_code in (401, 403) and "application/json" in r.headers.get("Content-Type", ""):
                return port
        except requests.exceptions.ConnectionError:
            continue
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def fetch_trajectories(port: int, csrf_token: str) -> dict:
    url = f"http://127.0.0.1:{port}/{SERVICE}/GetAllCascadeTrajectories"
    r = requests.post(
        url,
        headers={"Content-Type": "application/json", "x-codeium-csrf-token": csrf_token},
        json={},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def fetch_full_trajectory(port: int, csrf_token: str, cascade_id: str) -> list[dict]:
    """Fetch all steps for a conversation via GetCascadeTrajectory.
    Returns the steps list, or empty list on failure."""
    url = f"http://127.0.0.1:{port}/{SERVICE}/GetCascadeTrajectory"
    try:
        r = requests.post(
            url,
            headers={"Content-Type": "application/json", "x-codeium-csrf-token": csrf_token},
            json={"cascadeId": cascade_id},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("trajectory", {}).get("steps", [])
    except Exception as e:
        log.warning(f"fetch_full_trajectory({cascade_id[:8]}): {e}")
        return []


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


# ---------------------------------------------------------------------------
# Note building
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text).strip("-")
    return text[:60]


def parse_steps(steps: list[dict]) -> dict:
    """Extract user prompts, AI responses, files changed, and commands from steps."""
    user_messages = []
    ai_responses  = []
    files_changed = []
    commands_run  = []

    for step in steps:
        t = step.get("type", "")

        if t == "CORTEX_STEP_TYPE_USER_INPUT":
            text = step.get("userInput", {}).get("userResponse", "").strip()
            if text:
                user_messages.append(text)

        elif t == "CORTEX_STEP_TYPE_PLANNER_RESPONSE":
            # Prefer modifiedResponse (post-edit), fall back to response
            pr = step.get("plannerResponse", {})
            text = (pr.get("modifiedResponse") or pr.get("response") or "").strip()
            if text:
                ai_responses.append(text)

        elif t == "CORTEX_STEP_TYPE_CODE_ACTION":
            spec = step.get("codeAction", {}).get("actionSpec", {})
            path = spec.get("absoluteUri", "") or spec.get("path", "")
            if path:
                path = path.replace("file:///", "").replace("/", "\\")
                if path not in files_changed:
                    files_changed.append(path)

        elif t == "CORTEX_STEP_TYPE_RUN_COMMAND":
            rc = step.get("runCommand", {})
            cmd = rc.get("commandLine") or rc.get("proposedCommandLine", "")
            if cmd and cmd not in commands_run:
                commands_run.append(cmd)

    return {
        "user_messages": user_messages,
        "ai_responses":  ai_responses,
        "files_changed": files_changed,
        "commands_run":  commands_run,
    }


def build_thread(steps: list[dict]) -> list[tuple[str, str]]:
    """Build an interleaved [(role, text)] list from steps for the full conversation.
    role is 'user' or 'cascade'. Truncates each turn to 800 chars."""
    thread = []
    for step in steps:
        t = step.get("type", "")
        if t == "CORTEX_STEP_TYPE_USER_INPUT":
            text = step.get("userInput", {}).get("userResponse", "").strip()
            if not text:
                continue
            text = text.replace("\n", " ")
            if len(text) > 800:
                text = text[:800] + "\u2026"
            thread.append(("user", text))
        elif t == "CORTEX_STEP_TYPE_PLANNER_RESPONSE":
            pr = step.get("plannerResponse", {})
            text = (pr.get("modifiedResponse") or pr.get("response") or "").strip()
            if not text:
                continue
            if len(text) > 800:
                text = text[:800] + "\u2026"
            thread.append(("cascade", text))
    return thread


def build_note(uuid: str, item: dict, steps: list[dict]) -> str:
    title         = item.get("summary") or item.get("title") or "Untitled Conversation"
    step_count    = item.get("stepCount", 0)
    created_at    = item.get("createdTime", "")
    model         = item.get("lastGeneratorModelUid", "")
    trajectory_id = item.get("trajectoryId", "")
    status        = item.get("status", "")

    workspace = ""
    ws_list = item.get("workspaces", [])
    if ws_list:
        repo = ws_list[0].get("repository", {})
        workspace = repo.get("computedName", "") or ws_list[0].get("workspaceFolderAbsoluteUri", "")

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    last_user_input = item.get("lastUserInputTime", "")
    last_input_str = ""
    if last_user_input:
        try:
            dt2 = datetime.fromisoformat(last_user_input.replace("Z", "+00:00"))
            last_input_str = dt2.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            pass

    parsed = parse_steps(steps)
    thread  = build_thread(steps)

    lines = [
        f"# {title}",
        "",
        f"**Trajectory ID:** `{trajectory_id}`",
        f"**UUID:** `{uuid}`",
        f"**Steps:** {step_count}",
        f"**Date:** {date_str}",
    ]
    if workspace:
        lines.append(f"**Workspace:** {workspace}")
    if model:
        lines.append(f"**Model:** {model}")
    if last_input_str:
        lines.append(f"**Last Activity:** {last_input_str}")
    lines.append("")

    # --- Conversation thread ---
    lines.append("## Conversation")
    lines.append("")
    if thread:
        for role, text in thread:
            if role == "user":
                lines.append(f"**User:** {text}")
            else:
                lines.append(f"**Cascade:** {text}")
            lines.append("")
    else:
        lines.append("*No conversation content captured.*")
        lines.append("")

    # --- Key Outcomes ---
    lines.append("## Key Outcomes")
    lines.append("")
    has_outcomes = False

    if parsed["files_changed"]:
        has_outcomes = True
        lines.append("**Files changed:**")
        for f in parsed["files_changed"][:15]:
            lines.append(f"- `{f}`")
        if len(parsed["files_changed"]) > 15:
            lines.append(f"- *\u2026and {len(parsed['files_changed']) - 15} more*")
        lines.append("")

    if parsed["commands_run"]:
        has_outcomes = True
        lines.append("**Commands run:**")
        for cmd in parsed["commands_run"][:8]:
            short_cmd = cmd.strip()
            if len(short_cmd) > 120:
                short_cmd = short_cmd[:120] + "\u2026"
            lines.append(f"- `{short_cmd}`")
        if len(parsed["commands_run"]) > 8:
            lines.append(f"- *\u2026and {len(parsed['commands_run']) - 8} more*")
        lines.append("")

    if not has_outcomes:
        lines.append("*No file changes or commands captured.*")
        lines.append("")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append("---")
    lines.append(f"*Auto-exported by Windsurf watcher on {now_str}*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Export logic
# ---------------------------------------------------------------------------

def export_conversation(uuid: str, item: dict, steps: list[dict], index: dict) -> str | None:
    """Build and write note. Returns note path or None on failure."""
    VAULT_CHATS_DIR.mkdir(parents=True, exist_ok=True)

    title = item.get("summary") or item.get("title") or "Untitled Conversation"
    slug = slugify(title)
    short_id = uuid[:8]
    filename = f"{slug}_{short_id}.md"
    note_path = VAULT_CHATS_DIR / filename

    content = build_note(uuid, item, steps)
    try:
        note_path.write_text(content, encoding="utf-8")
    except Exception as e:
        log.error(f"Failed to write {note_path}: {e}")
        return None

    # Update index
    trajectory_id = item.get("trajectoryId", "")
    workspace = ""
    ws_list = item.get("workspaces", [])
    if ws_list:
        repo = ws_list[0].get("repository", {})
        workspace = repo.get("computedName", "") or ws_list[0].get("workspaceFolderAbsoluteUri", "")

    now_iso = datetime.now(timezone.utc).isoformat()
    if uuid not in index["conversations"]:
        index["conversations"][uuid] = {}
    conv = index["conversations"][uuid]
    conv.update({
        "uuid": uuid,
        "trajectory_id": trajectory_id,
        "title": title,
        "category": "cascade",
        "step_count": item.get("stepCount", 0),
        "workspace": workspace,
        "created_at": item.get("createdTime"),
        "last_modified": item.get("lastModifiedTime"),
        "exported": True,
        "export_path": str(note_path),
        "exported_at": now_iso,
    })

    return str(note_path)


# ---------------------------------------------------------------------------
# Poll cycle
# ---------------------------------------------------------------------------

def poll_once(ls_port: int, csrf_token: str) -> int:
    """Fetch trajectories, export any new/updated ones. Returns count exported."""
    try:
        data = fetch_trajectories(ls_port, csrf_token)
    except Exception as e:
        log.warning(f"fetch_trajectories failed: {e}")
        return 0

    summaries: dict = data.get("trajectorySummaries", {})
    index = load_index()
    exported = 0

    for uuid, item in summaries.items():
        last_modified = item.get("lastModifiedTime", "")
        existing = index.get("conversations", {}).get(uuid, {})
        prev_modified = existing.get("last_modified", "")
        prev_exported = existing.get("exported", False)

        # Export if: never exported OR conversation was modified after the last export
        exported_at = existing.get("exported_at", "")
        if prev_exported and last_modified and exported_at:
            # Only re-export if the conversation was modified AFTER we last exported it
            needs_export = last_modified > exported_at
        else:
            needs_export = not prev_exported
        if not needs_export:
            continue

        # Fetch full conversation steps
        steps = fetch_full_trajectory(ls_port, csrf_token, uuid)

        note_path = export_conversation(uuid, item, steps, index)
        if note_path:
            log.info(f"Exported: {Path(note_path).name}  [{uuid[:8]}]")
            exported += 1

    if exported:
        save_index(index)

    return exported


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Windsurf → Obsidian watcher")
    parser.add_argument("--once", action="store_true", help="Single pass, then exit")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL, help="Poll interval in seconds")
    args = parser.parse_args()

    log.info("=== Windsurf Obsidian watcher started ===")
    log.info(f"Vault: {VAULT_CHATS_DIR}")
    log.info(f"Interval: {args.interval}s  |  Mode: {'once' if args.once else 'loop'}")

    ls_info = None
    ls_cache_ts = 0.0

    def get_ls(force: bool = False):
        nonlocal ls_info, ls_cache_ts
        if force or not ls_info or (time.time() - ls_cache_ts > 300):
            ls_info = get_ls_info()
            ls_cache_ts = time.time()
        return ls_info

    while True:
        info = get_ls()
        if not info:
            log.warning("Windsurf language server not found — is Windsurf running?")
        else:
            port, csrf = info
            try:
                count = poll_once(port, csrf)
                if count:
                    log.info(f"Poll complete: {count} note(s) written.")
                else:
                    log.debug("Poll complete: nothing new.")
            except Exception as e:
                log.error(f"Poll error: {e}")
                ls_info = None  # force rediscovery next time

        if args.once:
            break

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
