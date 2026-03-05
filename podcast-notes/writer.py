"""
Write generated Obsidian notes to the vault with POSIX-compliant,
OneDrive-safe filenames.
"""

from __future__ import annotations

import re
from pathlib import Path

import config


def sanitize_filename(raw: str) -> str:
    """
    Convert a raw episode title into a POSIX-compliant, OneDrive-safe filename.

    Rules applied:
      1. Replace '#' with dash
      2. Replace em-dash (—), en-dash (–) with '-'
      3. Strip characters illegal on POSIX / OneDrive: ? * : " < > | \\ /
      4. Replace spaces and underscores with '-'
      5. Collapse consecutive dashes
      6. Remove leading / trailing dashes
      7. Truncate to 200 chars (OneDrive path-length safety)
    """
    name = raw
    name = name.replace("#", "-")
    name = name.replace("—", "-").replace("–", "-")
    # Remove illegal chars
    name = re.sub(r'[?*:"<>|\\/_]', "", name)
    # Spaces → dashes
    name = name.replace(" ", "-")
    # Strip non-ASCII-friendly chars but keep letters, digits, dashes, dots
    name = re.sub(r"[^\w\-.]", "", name, flags=re.ASCII)
    # Collapse dashes
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-.")
    # Truncate
    if len(name) > 200:
        name = name[:200].rstrip("-.")
    return name


def build_filename(episode_number: int, guest: str, title: str) -> str:
    """
    Build the full .md filename for an episode.
    Example: Modern-Wisdom-1066-Dr-Kathryn-Paige-Harden-The-Genetics-of-Evil-Are-People-Born-Bad.md
    """
    raw = f"Modern Wisdom - {episode_number} - {guest}.md" if guest else f"Modern Wisdom - {episode_number}.md"
    return sanitize_filename_keep_format(raw)


def write_note(
    content: str,
    episode_number: int,
    guest: str,
    title: str,
) -> Path:
    """
    Write the markdown content to the Obsidian vault and return the
    resulting file path.
    """
    out_dir = config.output_dir()
    filename = build_filename(episode_number, guest, title)
    filepath = out_dir / filename

    filepath.write_text(content, encoding="utf-8")
    return filepath


_WINDOWS_ILLEGAL_CHARS_RE = re.compile(r"[<>:\"/\\|?*]")


def sanitize_filename_keep_format(raw: str) -> str:
    name = raw
    name = name.replace("\u0000", "")
    name = _WINDOWS_ILLEGAL_CHARS_RE.sub("", name)
    name = re.sub(r"\s{2,}", " ", name)
    name = name.strip(" .")
    if len(name) > 200:
        name = name[:200].rstrip(" .")
    return name


def build_processed_filename(episode_number: int, guest: str) -> str:
    raw = f"Modern Wisdom - {episode_number} — {guest}.md" if guest else f"Modern Wisdom - {episode_number}.md"
    return sanitize_filename_keep_format(raw)
