"""
export_windsurf_chats.py

Helper script for the /export-chats Windsurf workflow.
Manages an index.json that tracks which Windsurf conversations have been
exported to the Obsidian vault.

Windsurf trajectory data is server-side only; UUIDs must be provided manually
(copy from the Windsurf chat history panel) or via --add.

Usage:
  python export_windsurf_chats.py --list-pending
      Print all conversations in the index where exported=false.

  python export_windsurf_chats.py --add "<uuid>" "<category>" "<title>"
      Register a new conversation UUID in the index (exported=false).

  python export_windsurf_chats.py --mark-exported "<uuid>" "<category>" "<title>"
      Mark a conversation as exported in the index.

  python export_windsurf_chats.py --status
      Print a summary of all tracked conversations.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
INDEX_FILE = SCRIPT_DIR / "index.json"


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
_default_vault = _DOTENV.get("OBSIDIAN_VAULT_PATH") or os.environ.get("OBSIDIAN_VAULT")
if not _default_vault:
    raise SystemExit(
        "ERROR: OBSIDIAN_VAULT_PATH not set in .env or OBSIDIAN_VAULT environment variable.\n"
        "Create a .env file in the script directory with:\n"
        '  OBSIDIAN_VAULT_PATH=C:\\\\Users\\\\YOUR_NAME\\\\...\\\\Your-Vault'
    )
OBSIDIAN_CHATS_DIR = Path(_default_vault) / "Chats"

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
    print(f"Index saved → {INDEX_FILE}")



# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_add(uuid: str, category: str, title: str) -> None:
    index = load_index()
    if uuid in index["conversations"]:
        print(f"Already in index: {uuid} — {index['conversations'][uuid]['title']}")
        return
    index["conversations"][uuid] = {
        "uuid": uuid,
        "title": title,
        "category": category,
        "exported": False,
        "export_path": None,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    save_index(index)
    print(f"Added to index: {uuid} — {title}")


def cmd_status() -> None:
    index = load_index()
    convos = list(index["conversations"].values())
    exported = [c for c in convos if c["exported"]]
    pending = [c for c in convos if not c["exported"]]
    print(f"Total tracked: {len(convos)}  |  Exported: {len(exported)}  |  Pending: {len(pending)}")
    if exported:
        print("\nExported:")
        for c in exported:
            print(f"  [x] {c['uuid']}  —  {c['title']}")
    if pending:
        print("\nPending:")
        for c in pending:
            print(f"  [ ] {c['uuid']}  —  {c['title']}")


def cmd_mark_exported(uuid: str, category: str, title: str) -> None:
    index = load_index()
    slug = slugify(title)
    short = uuid[:8]
    filename = f"{slug}_{short}.md"
    export_path = str(OBSIDIAN_CHATS_DIR / filename)

    if uuid in index["conversations"]:
        index["conversations"][uuid]["exported"] = True
        index["conversations"][uuid]["export_path"] = export_path
        index["conversations"][uuid]["exported_at"] = datetime.now(timezone.utc).isoformat()
    else:
        index["conversations"][uuid] = {
            "uuid": uuid,
            "title": title,
            "category": category,
            "exported": True,
            "export_path": export_path,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }

    save_index(index)
    print(f"Marked exported: {uuid} → {export_path}")


def cmd_list_pending() -> None:
    index = load_index()
    pending = [v for v in index["conversations"].values() if not v["exported"]]
    if not pending:
        print("No pending conversations.")
        return
    print(f"{len(pending)} pending export:\n")
    for c in pending:
        print(f"  [{c['category']}] {c['uuid']}  —  {c['title']}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Windsurf chat export index manager")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--add", nargs=3, metavar=("UUID", "CATEGORY", "TITLE"),
                       help="Register a new UUID in the index (exported=false)")
    group.add_argument("--mark-exported", nargs=3, metavar=("UUID", "CATEGORY", "TITLE"),
                       help="Mark a conversation as exported")
    group.add_argument("--list-pending", action="store_true", help="List unexported conversations")
    group.add_argument("--status", action="store_true", help="Print full index status")
    args = parser.parse_args()

    if args.add:
        cmd_add(*args.add)
    elif args.mark_exported:
        cmd_mark_exported(*args.mark_exported)
    elif args.list_pending:
        cmd_list_pending()
    elif args.status:
        cmd_status()


if __name__ == "__main__":
    main()
