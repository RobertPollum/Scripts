"""
hook_export.py

Windsurf Cascade hook: post_cascade_response_with_transcript

Triggered automatically after each Cascade response. Reads the JSONL
transcript file provided by Windsurf, extracts conversation metadata and
content, and writes/updates an Obsidian note in the Chats vault directory.

Usage (invoked by Windsurf hook system, not manually):
  python hook_export.py          # reads JSON from stdin

Manual test:
  echo '{"agent_action_name":"post_cascade_response_with_transcript","tool_info":{"transcript_path":"C:/path/to/transcript.jsonl"}}' | python hook_export.py

Cross-platform: works on Windows, macOS, Linux. Vault path is resolved from
an environment variable OBSIDIAN_VAULT or the hardcoded fallback below.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration — override via environment variables for portability
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent


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
DEFAULT_VAULT_PATH_POSIX = os.path.expanduser("~/Robert-Vault")


def get_vault_chats_dir() -> Path:
    env = os.environ.get("OBSIDIAN_VAULT") or _DOTENV.get("OBSIDIAN_VAULT_PATH")
    if env:
        return Path(env) / "Chats"
    if sys.platform == "win32":
        raise SystemExit(
            "ERROR: OBSIDIAN_VAULT_PATH not set in .env or OBSIDIAN_VAULT environment variable.\n"
            "Create a .env file in the script directory with:\n"
            '  OBSIDIAN_VAULT_PATH=C:\\\\Users\\\\YOUR_NAME\\\\...\\\\Your-Vault'
        )
    return Path(DEFAULT_VAULT_PATH_POSIX) / "Chats"


# Index file lives alongside this script
INDEX_FILE = Path(__file__).parent / "index.json"

# ---------------------------------------------------------------------------
# Helpers
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


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

def parse_transcript(jsonl_path: str) -> dict:
    """Parse the Windsurf JSONL transcript file.

    Returns a dict with:
      trajectory_id  — derived from filename
      steps          — list of raw step dicts
      user_messages  — list of user prompt strings
      ai_responses   — list of planner response strings
      files_changed  — list of file paths written
      commands_run   — list of command strings executed
      first_ts       — ISO timestamp of first step (if available)
      title          — best-effort title from first user message
    """
    path = Path(jsonl_path)
    trajectory_id = path.stem  # filename without .jsonl

    steps = []
    user_messages = []
    ai_responses = []
    files_changed = []
    commands_run = []
    first_ts = None

    if not path.exists():
        return {
            "trajectory_id": trajectory_id,
            "steps": [],
            "user_messages": [],
            "ai_responses": [],
            "files_changed": [],
            "commands_run": [],
            "first_ts": None,
            "title": "Untitled Conversation",
        }

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                step = json.loads(line)
            except json.JSONDecodeError:
                continue

            steps.append(step)
            step_type = step.get("type", "")

            # Extract timestamp (not always present)
            if first_ts is None and step.get("timestamp"):
                first_ts = step["timestamp"]

            # User input
            if step_type == "user_input":
                ui = step.get("user_input", {})
                prompt = ui.get("user_response", "")
                if prompt:
                    user_messages.append(prompt)

            # AI planner responses
            elif step_type == "planner_response":
                pr = step.get("planner_response", {})
                response = pr.get("response", "")
                if response:
                    ai_responses.append(response)

            # File writes
            elif step_type == "code_action":
                ca = step.get("code_action", {})
                fpath = ca.get("path", "")
                if fpath and fpath not in files_changed:
                    files_changed.append(fpath)

            # Commands run
            elif step_type == "terminal_action":
                ta = step.get("terminal_action", {})
                cmd = ta.get("command", "") or ta.get("command_line", "")
                if cmd and cmd not in commands_run:
                    commands_run.append(cmd)

    # Derive title from first user message
    title = "Untitled Conversation"
    if user_messages:
        first = user_messages[0]
        # Take first non-empty line, cap at 80 chars
        for line in first.splitlines():
            line = line.strip()
            if line:
                title = line[:80]
                break

    return {
        "trajectory_id": trajectory_id,
        "steps": steps,
        "user_messages": user_messages,
        "ai_responses": ai_responses,
        "files_changed": files_changed,
        "commands_run": commands_run,
        "first_ts": first_ts,
        "title": title,
    }


# ---------------------------------------------------------------------------
# Note generation
# ---------------------------------------------------------------------------

def build_note(data: dict, uuid: str, workspace: str) -> str:
    """Build the Obsidian markdown note content."""
    title = data["title"]
    trajectory_id = data["trajectory_id"]
    steps_count = len(data["steps"])
    first_ts = data["first_ts"]

    # Date
    if first_ts:
        try:
            # Handle both epoch ms and ISO strings
            if isinstance(first_ts, (int, float)):
                dt = datetime.fromtimestamp(first_ts / 1000, tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(str(first_ts).replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [
        f"# {title}",
        "",
        f"**Trajectory ID:** `{trajectory_id}`",
        f"**UUID:** `{uuid}`",
        f"**Steps:** {steps_count}",
        f"**Date:** {date_str}",
    ]
    if workspace:
        lines.append(f"**Workspace:** {workspace}")
    lines.append("")

    # Summary section — use last AI response as summary if available
    lines.append("## Summary")
    lines.append("")
    if data["ai_responses"]:
        # Use the final planner response, truncated
        summary = data["ai_responses"][-1].strip()
        if len(summary) > 500:
            summary = summary[:500] + "…"
        lines.append(summary)
    else:
        lines.append("*No AI response text captured in transcript.*")
    lines.append("")

    # User prompts (first 3)
    if data["user_messages"]:
        lines.append("## User Prompts")
        lines.append("")
        for i, msg in enumerate(data["user_messages"][:3], 1):
            short = msg.strip().replace("\n", " ")
            if len(short) > 200:
                short = short[:200] + "…"
            lines.append(f"{i}. {short}")
        if len(data["user_messages"]) > 3:
            lines.append(f"*…and {len(data['user_messages']) - 3} more prompts*")
        lines.append("")

    # Key outcomes
    lines.append("## Key Outcomes")
    lines.append("")
    has_outcomes = False

    if data["files_changed"]:
        has_outcomes = True
        lines.append("**Files changed:**")
        for f in data["files_changed"][:10]:
            lines.append(f"- `{f}`")
        if len(data["files_changed"]) > 10:
            lines.append(f"- *…and {len(data['files_changed']) - 10} more*")
        lines.append("")

    if data["commands_run"]:
        has_outcomes = True
        lines.append("**Commands run:**")
        for cmd in data["commands_run"][:5]:
            short_cmd = cmd.strip()
            if len(short_cmd) > 120:
                short_cmd = short_cmd[:120] + "…"
            lines.append(f"- `{short_cmd}`")
        if len(data["commands_run"]) > 5:
            lines.append(f"- *…and {len(data['commands_run']) - 5} more*")
        lines.append("")

    if not has_outcomes:
        lines.append("*No file changes or commands captured in transcript.*")
        lines.append("")

    lines.append(f"---")
    lines.append(f"*Auto-exported by Windsurf hook on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main hook logic
# ---------------------------------------------------------------------------

def main() -> None:
    # Debug log file — captures every invocation so we can diagnose issues
    debug_log = Path(__file__).parent / "hook_debug.log"

    def dlog(msg: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with open(debug_log, "a", encoding="utf-8") as lf:
            lf.write(f"[{ts}] {msg}\n")

    dlog("=== hook_export invoked ===")

    # Read JSON input from stdin (provided by Windsurf)
    try:
        raw = sys.stdin.read()
        dlog(f"stdin raw ({len(raw)} chars): {raw[:500]}")
        payload = json.loads(raw)
    except Exception as e:
        dlog(f"ERROR: failed to parse stdin JSON: {e}")
        print(f"[hook_export] ERROR: failed to parse stdin JSON: {e}", file=sys.stderr)
        sys.exit(0)  # exit 0 so we never block Cascade

    agent_action = payload.get("agent_action_name", "")
    dlog(f"agent_action_name={agent_action!r}, keys={list(payload.keys())}")
    if agent_action != "post_cascade_response_with_transcript":
        dlog(f"Skipping: action {agent_action!r} is not post_cascade_response_with_transcript")
        sys.exit(0)

    tool_info = payload.get("tool_info", {})
    transcript_path = tool_info.get("transcript_path", "")
    dlog(f"transcript_path={transcript_path!r}, tool_info keys={list(tool_info.keys())}")
    if not transcript_path:
        dlog("ERROR: no transcript_path in tool_info")
        print("[hook_export] ERROR: no transcript_path in tool_info", file=sys.stderr)
        sys.exit(0)

    # Parse transcript
    data = parse_transcript(transcript_path)
    trajectory_id = data["trajectory_id"]
    dlog(f"transcript parsed: trajectory_id={trajectory_id!r}, steps={len(data['steps'])}, title={data['title']!r}")

    # Look up index for this trajectory to get UUID and workspace
    index = load_index()
    uuid = trajectory_id  # fallback: use trajectory_id as identifier
    workspace = ""

    for uid, conv in index.get("conversations", {}).items():
        if conv.get("trajectory_id") == trajectory_id or uid == trajectory_id:
            uuid = uid
            workspace = conv.get("workspace", "")
            break

    # Build note
    note_content = build_note(data, uuid, workspace)

    # Determine output path
    vault_chats_dir = get_vault_chats_dir()
    try:
        vault_chats_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[hook_export] ERROR: cannot create vault dir {vault_chats_dir}: {e}", file=sys.stderr)
        sys.exit(0)

    slug = slugify(data["title"])
    short_id = uuid[:8] if len(uuid) >= 8 else uuid
    filename = f"{slug}_{short_id}.md"
    note_path = vault_chats_dir / filename

    # Write note (overwrite on each response — keeps it updated)
    try:
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(note_content)
        dlog(f"Note written: {note_path}")
    except Exception as e:
        dlog(f"ERROR: failed to write note: {e}")
        print(f"[hook_export] ERROR: failed to write note: {e}", file=sys.stderr)
        sys.exit(0)

    # Update index
    step_count = len(data["steps"])
    if uuid not in index["conversations"]:
        index["conversations"][uuid] = {
            "uuid": uuid,
            "trajectory_id": trajectory_id,
            "title": data["title"],
            "category": "cascade",
            "step_count": step_count,
            "workspace": workspace,
            "created_at": data["first_ts"],
            "exported": True,
            "export_path": str(note_path),
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        index["conversations"][uuid]["exported"] = True
        index["conversations"][uuid]["export_path"] = str(note_path)
        index["conversations"][uuid]["step_count"] = step_count
        index["conversations"][uuid]["exported_at"] = datetime.now(timezone.utc).isoformat()

    try:
        save_index(index)
    except Exception as e:
        print(f"[hook_export] WARNING: index save failed: {e}", file=sys.stderr)

    print(f"[hook_export] Exported: {note_path}")
    sys.exit(0)


if __name__ == "__main__":
    main()
