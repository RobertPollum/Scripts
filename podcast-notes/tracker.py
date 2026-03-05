"""
Human-readable CSV tracker for processed podcast episodes.

File: processed_episodes.csv (lives in the podcast-notes directory).
Columns: episode_number, guest, title, url, processed_at, status
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List

import config

FIELDNAMES = [
    "episode_number",
    "guest",
    "title",
    "url",
    "processed_at",
    "status",
]


@dataclass
class TrackerEntry:
    episode_number: int
    guest: str
    title: str
    url: str
    processed_at: str
    status: str  # "completed" | "failed"


def _ensure_file() -> None:
    """Create the CSV with headers if it doesn't exist yet."""
    if not os.path.exists(config.TRACKER_PATH):
        with open(config.TRACKER_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()


def load_tracker() -> Dict[int, TrackerEntry]:
    """Load all tracker entries keyed by episode number."""
    _ensure_file()
    entries: Dict[int, TrackerEntry] = {}
    with open(config.TRACKER_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ep_num = int(row["episode_number"])
            except (ValueError, KeyError):
                continue
            entries[ep_num] = TrackerEntry(
                episode_number=ep_num,
                guest=row.get("guest", ""),
                title=row.get("title", ""),
                url=row.get("url", ""),
                processed_at=row.get("processed_at", ""),
                status=row.get("status", ""),
            )
    return entries


def is_processed(episode_number: int) -> bool:
    """Return True if the episode has already been successfully processed."""
    entries = load_tracker()
    entry = entries.get(episode_number)
    return entry is not None and entry.status == "completed"


def mark_processed(
    episode_number: int,
    guest: str,
    title: str,
    url: str,
    status: str = "completed",
) -> None:
    """Append (or update) an entry in the tracker."""
    entries = load_tracker()
    entries[episode_number] = TrackerEntry(
        episode_number=episode_number,
        guest=guest,
        title=title,
        url=url,
        processed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        status=status,
    )
    _write_all(entries)


def get_processed_list() -> List[TrackerEntry]:
    """Return all tracker entries sorted by episode number descending."""
    entries = load_tracker()
    return sorted(entries.values(), key=lambda e: e.episode_number, reverse=True)


def _write_all(entries: Dict[int, TrackerEntry]) -> None:
    """Rewrite the full CSV (keeps it sorted and deduped)."""
    _ensure_file()
    sorted_entries = sorted(entries.values(), key=lambda e: e.episode_number, reverse=True)
    with open(config.TRACKER_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for entry in sorted_entries:
            writer.writerow({
                "episode_number": entry.episode_number,
                "guest": entry.guest,
                "title": entry.title,
                "url": entry.url,
                "processed_at": entry.processed_at,
                "status": entry.status,
            })
