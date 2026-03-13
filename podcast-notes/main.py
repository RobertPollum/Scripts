#!/usr/bin/env python3
"""
Modern Wisdom Podcast → Obsidian Notes pipeline.

Usage:
    python main.py list                      # show available episodes & status
    python main.py status                    # show tracker contents

  Batch scraping (no API key needed):
    python main.py scrape --episode 1066     # scrape one episode to staging/
    python main.py scrape-latest --count 10  # batch scrape latest 10 unscraped
    python main.py scrape-all                # batch scrape entire catalog
    python main.py scrape-all --delay 12     # slower rate limit (12s between pages)

  Windsurf-credits workflow:
    python main.py write-note --episode 1066 --file note.md  # write finished note to vault

  API mode (needs OPENAI_API_KEY):
    python main.py process --episode 1066    # scrape + AI + write in one step
    python main.py process-latest --count 5  # latest N unprocessed
    python main.py process-all               # process every unprocessed episode
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
import time
from datetime import datetime
from pathlib import Path

import config
import scraper
import summarizer
import tracker
import writer

STAGING_DIR = Path(__file__).parent / "staging"
TEMPLATES_DIR = Path(__file__).parent / "templates"
EPISODE_TEMPLATE_PATH = TEMPLATES_DIR / "modern-wisdom-episode-template.md"
PROCESSED_DIR = Path(__file__).parent / "processed"


def _is_scraped(ep_num: int) -> bool:
    """Check if a transcript already exists in staging/."""
    return (STAGING_DIR / f"{ep_num}_transcript.txt").exists()


def _save_to_staging(ep: scraper.EpisodeMeta, transcript: str) -> None:
    """Write transcript + metadata to staging/."""
    STAGING_DIR.mkdir(exist_ok=True)
    (STAGING_DIR / f"{ep.number}_transcript.txt").write_text(transcript, encoding="utf-8")
    (STAGING_DIR / f"{ep.number}_meta.json").write_text(json.dumps({
        "number": ep.number,
        "title": ep.title,
        "guest": ep.guest,
        "slug": ep.slug,
        "url": ep.url,
    }, indent=2), encoding="utf-8")


def _staged_episode_numbers() -> list[int]:
    if not STAGING_DIR.exists():
        return []
    episode_nums: list[int] = []
    for p in STAGING_DIR.glob("*_meta.json"):
        try:
            episode_nums.append(int(p.stem.split("_", 1)[0]))
        except ValueError:
            continue
    return sorted(set(episode_nums))


def _load_staged_episode(ep_num: int) -> tuple[scraper.EpisodeMeta, str]:
    meta_file = STAGING_DIR / f"{ep_num}_meta.json"
    transcript_file = STAGING_DIR / f"{ep_num}_transcript.txt"

    if not meta_file.exists():
        raise FileNotFoundError(str(meta_file))
    if not transcript_file.exists():
        raise FileNotFoundError(str(transcript_file))

    meta_json = json.loads(meta_file.read_text(encoding="utf-8"))
    ep = scraper.EpisodeMeta(
        number=int(meta_json.get("number", ep_num)),
        title=str(meta_json.get("title", "")),
        guest=str(meta_json.get("guest", "")),
        slug=str(meta_json.get("slug", "")),
        url=str(meta_json.get("url", "")),
    )
    transcript = transcript_file.read_text(encoding="utf-8")
    return ep, transcript


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def process_episode(ep: scraper.EpisodeMeta, *, force: bool = False) -> bool:
    """
    Run the full pipeline for one episode.
    Returns True on success, False on failure.
    """
    if not force and tracker.is_processed(ep.number):
        print(f"  ⏭  Episode #{ep.number} already processed — skipping.")
        return True

    print(f"  📥  Scraping transcript for #{ep.number}: {ep.title}")
    try:
        transcript = scraper.get_transcript(ep.url)
    except Exception as exc:
        print(f"  ❌  Failed to scrape transcript: {exc}")
        tracker.mark_processed(ep.number, ep.guest, ep.title, ep.url, status="failed")
        return False

    print(f"  🤖  Generating notes with model '{config.OPENAI_MODEL}'...")
    try:
        notes_md = summarizer.generate_notes(transcript, ep)
    except Exception as exc:
        print(f"  ❌  LLM generation failed: {exc}")
        tracker.mark_processed(ep.number, ep.guest, ep.title, ep.url, status="failed")
        return False

    print(f"  💾  Writing note to vault...")
    filepath = writer.write_note(notes_md, ep.number, ep.guest, ep.title)
    print(f"  ✅  Saved → {filepath}")

    tracker.mark_processed(ep.number, ep.guest, ep.title, ep.url, status="completed")
    return True


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_list(args: argparse.Namespace) -> None:
    """List available episodes and their processing status."""
    print("Fetching episode list from Podscripts…")
    episodes = scraper.get_episode_list(max_pages=args.pages)
    processed = tracker.load_tracker()

    print(f"\n{'EP':>6}  {'STATUS':>9}  TITLE")
    print("-" * 80)
    for ep in episodes:
        entry = processed.get(ep.number)
        if entry and entry.status == "completed":
            status = "    ✅"
        elif entry and entry.status == "failed":
            status = "    ❌"
        else:
            status = "    ⬜"
        print(f"#{ep.number:>5}  {status}  {ep.guest} — {ep.title}" if ep.guest else f"#{ep.number:>5}  {status}  {ep.title}")


def cmd_process(args: argparse.Namespace) -> None:
    """Process a single episode by number."""
    ep_num = args.episode
    print(f"Looking up episode #{ep_num}…")
    ep = scraper.get_episode_by_number(ep_num)
    if not ep:
        print(f"Episode #{ep_num} not found on Podscripts.")
        sys.exit(1)

    ok = process_episode(ep, force=args.force)
    sys.exit(0 if ok else 1)


def cmd_process_latest(args: argparse.Namespace) -> None:
    """Process the latest N unprocessed episodes."""
    count = args.count
    print(f"Fetching episode list…")
    episodes = scraper.get_episode_list(max_pages=args.pages)

    to_process = [
        ep for ep in episodes if not tracker.is_processed(ep.number)
    ][:count]

    if not to_process:
        print("All episodes already processed!")
        return

    print(f"Processing {len(to_process)} episode(s)…\n")
    for ep in to_process:
        print(f"── Episode #{ep.number} ──")
        process_episode(ep)
        print()


def cmd_process_all(args: argparse.Namespace) -> None:
    """Process every unprocessed episode."""
    print("Fetching full episode list…")
    episodes = scraper.get_episode_list(max_pages=args.pages)

    to_process = [ep for ep in episodes if not tracker.is_processed(ep.number)]

    if not to_process:
        print("All episodes already processed!")
        return

    print(f"Processing {len(to_process)} episode(s)…\n")
    successes = 0
    failures = 0
    for ep in to_process:
        print(f"── Episode #{ep.number} ──")
        ok = process_episode(ep)
        if ok:
            successes += 1
        else:
            failures += 1
        print()

    print(f"\nDone: {successes} succeeded, {failures} failed.")


def cmd_status(_args: argparse.Namespace) -> None:
    """Show the current tracker contents."""
    entries = tracker.get_processed_list()
    if not entries:
        print("No episodes have been processed yet.")
        return

    print(f"\n{'EP':>6}  {'STATUS':>9}  {'PROCESSED AT':<26}  TITLE")
    print("-" * 90)
    for e in entries:
        status = "✅" if e.status == "completed" else "❌"
        print(f"#{e.episode_number:>5}  {status:>9}  {e.processed_at:<26}  {e.guest} — {e.title}" if e.guest else f"#{e.episode_number:>5}  {status:>9}  {e.processed_at:<26}  {e.title}")


def cmd_scrape(args: argparse.Namespace) -> None:
    """
    Scrape a single episode transcript and save it to staging/.
    Outputs a JSON metadata file + a plain-text transcript file.
    Used by the Windsurf-credits workflow so Cascade can do the AI step.
    """
    ep_num = args.episode
    print(f"Looking up episode #{ep_num}…")
    ep = scraper.get_episode_by_number(ep_num)
    if not ep:
        print(f"Episode #{ep_num} not found on Podscripts.")
        sys.exit(1)

    if not args.force and (tracker.is_processed(ep.number) or _is_scraped(ep.number)):
        print(f"Episode #{ep.number} already scraped — use --force to re-scrape.")
        sys.exit(0)

    print(f"Scraping transcript for #{ep.number}: {ep.title}")
    try:
        transcript = scraper.get_transcript(ep.url)
    except Exception as exc:
        print(f"Failed to scrape transcript: {exc}")
        sys.exit(1)

    _save_to_staging(ep, transcript)

    print(f"\nTranscript saved  → staging/{ep.number}_transcript.txt")
    print(f"Metadata saved    → staging/{ep.number}_meta.json")
    print(f"Transcript length → {len(transcript):,} chars")
    print(f"\nNext step: have Cascade (or any LLM) generate the note, then run:")
    print(f"  python main.py write-note --episode {ep.number} --file <generated_note.md>")


def cmd_scrape_latest(args: argparse.Namespace) -> None:
    """Batch scrape the latest N unscraped episode transcripts to staging/."""
    count = args.count
    delay = args.delay

    print("Fetching episode list from Podscripts…")
    episodes = scraper.get_episode_list(
        max_pages=args.pages,
        progress_cb=lambda pg, n: print(f"  page {pg} … {n} episodes found", end="\r"),
    )
    print()

    to_scrape = [
        ep for ep in episodes
        if not _is_scraped(ep.number) and not tracker.is_processed(ep.number)
    ][:count]

    if not to_scrape:
        print("All episodes already scraped!")
        return

    _run_batch_scrape(to_scrape, delay)


def cmd_scrape_all(args: argparse.Namespace) -> None:
    """Batch scrape every unscraped episode transcript to staging/."""
    delay = args.delay

    print("Fetching full episode catalog from Podscripts…")
    episodes = scraper.get_episode_list(
        max_pages=args.pages,
        progress_cb=lambda pg, n: print(f"  page {pg} … {n} episodes found", end="\r"),
    )
    print()

    to_scrape = [
        ep for ep in episodes
        if not _is_scraped(ep.number) and not tracker.is_processed(ep.number)
    ]

    if args.force:
        to_scrape = list(episodes)

    if not to_scrape:
        print("All episodes already scraped!")
        return

    _run_batch_scrape(to_scrape, delay)


def _run_batch_scrape(episodes: list[scraper.EpisodeMeta], delay: float) -> None:
    """Execute batch scraping with progress output and rate limiting."""
    total = len(episodes)
    successes = 0
    failures = 0

    print(f"Batch scraping {total} episode(s)  [delay={delay}s between pages]\n")

    def on_success(ep: scraper.EpisodeMeta, transcript: str) -> None:
        nonlocal successes
        successes += 1
        _save_to_staging(ep, transcript)
        print(f"  ✅ [{successes + failures}/{total}] #{ep.number} — {len(transcript):,} chars")

    def on_error(ep: scraper.EpisodeMeta, exc: Exception) -> None:
        nonlocal failures
        failures += 1
        print(f"  ❌ [{successes + failures}/{total}] #{ep.number} — {exc}")

    scraper.get_transcripts_batch(
        episodes,
        delay=delay,
        on_success=on_success,
        on_error=on_error,
    )

    print(f"\nBatch complete: {successes} succeeded, {failures} failed out of {total}.")
    print(f"Transcripts saved to: {STAGING_DIR.resolve()}")


def cmd_write_note(args: argparse.Namespace) -> None:
    """
    Write a pre-generated note to the Obsidian vault and update the tracker.
    Used after Cascade has produced the markdown via Windsurf credits.
    """
    ep_num = args.episode
    note_path = Path(args.file)

    if not note_path.exists():
        print(f"Note file not found: {note_path}")
        sys.exit(1)

    # Load metadata from staging (or fall back to scraping)
    meta_file = STAGING_DIR / f"{ep_num}_meta.json"
    if meta_file.exists():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        guest = meta.get("guest", "")
        title = meta.get("title", "")
        url = meta.get("url", "")
    else:
        print(f"No staging metadata for #{ep_num}, looking up on Podscripts…")
        ep = scraper.get_episode_by_number(ep_num)
        if not ep:
            print(f"Episode #{ep_num} not found.")
            sys.exit(1)
        guest, title, url = ep.guest, ep.title, ep.url

    notes_md = note_path.read_text(encoding="utf-8")
    filepath = writer.write_note(notes_md, ep_num, guest, title)
    tracker.mark_processed(ep_num, guest, title, url, status="completed")

    print(f"Note written → {filepath}")
    print(f"Tracker updated for episode #{ep_num}.")


def cmd_generate_processed(args: argparse.Namespace) -> None:
    """
    Generate Obsidian episode notes for every episode currently staged.
    Reads {episode}_meta.json + {episode}_transcript.txt from staging/.
    Writes final notes to processed/.

    Does not modify staging files.
    """
    if not EPISODE_TEMPLATE_PATH.exists():
        print(f"Template not found: {EPISODE_TEMPLATE_PATH}")
        sys.exit(1)

    if args.episode is not None:
        episode_nums = [args.episode]
    else:
        episode_nums = _staged_episode_numbers()

    if not episode_nums:
        print("No staged episodes found in staging/.")
        return

    template_md = EPISODE_TEMPLATE_PATH.read_text(encoding="utf-8")
    created_date = datetime.now().date().isoformat()

    PROCESSED_DIR.mkdir(exist_ok=True)

    total = len(episode_nums)
    successes = 0
    failures = 0
    skipped = 0

    for idx, ep_num in enumerate(episode_nums, start=1):
        try:
            ep, transcript = _load_staged_episode(ep_num)
        except Exception as exc:
            failures += 1
            print(f"  ❌ [{idx}/{total}] #{ep_num} — missing staged files: {exc}")
            continue

        guest_for_filename = (ep.guest or "Unknown Guest").strip()
        filename = writer.build_processed_filename(ep.number, guest_for_filename)
        out_path = PROCESSED_DIR / filename

        if out_path.exists() and not args.force:
            skipped += 1
            print(f"  ⏭  [{idx}/{total}] #{ep.number} — already generated")
            continue

        try:
            note_md = summarizer.generate_notes_from_template(
                transcript=transcript,
                meta=ep,
                template_markdown=template_md,
                created_date=created_date,
            )
            transcript_block = f"\nTRANSCRIPT:\n{transcript.strip()}\n"
            note_md = re.sub(r"\nTRANSCRIPT:\n[\s\S]*$", transcript_block, note_md.strip())
            out_path.write_text(note_md, encoding="utf-8")
            successes += 1
            print(f"  ✅ [{idx}/{total}] #{ep.number} — wrote {out_path.name}")
        except Exception as exc:
            failures += 1
            print(f"  ❌ [{idx}/{total}] #{ep.number} — generation failed: {exc}")

        if idx < total and args.delay > 0:
            time.sleep(args.delay)

    print(f"\nDone. {successes} succeeded, {skipped} skipped, {failures} failed.")


def cmd_summarize_staged(args: argparse.Namespace) -> None:
    """
    Option B batch mode: for every staged episode that has a transcript but
    has NOT yet been processed, call OpenAI to generate notes and write to vault.

    Skips scraping entirely — transcripts must already be in staging/.
    Respects OPENAI_RPM_LIMIT, OPENAI_TPM_LIMIT, OPENAI_RUN_TOKEN_CAP, and
    OPENAI_REQUEST_DELAY from .env / config.
    """
    if args.episode is not None:
        staged_nums = [args.episode]
    else:
        staged_nums = _staged_episode_numbers()

    if not staged_nums:
        print("No staged episodes found in staging/.")
        return

    if args.force:
        to_process = staged_nums
    else:
        to_process = [n for n in staged_nums if not tracker.is_processed(n)]

    if not to_process:
        print("All staged episodes are already processed. Use --force to re-process.")
        return

    limiter = summarizer.RateLimiter(
        rpm_limit=config.OPENAI_RPM_LIMIT,
        tpm_limit=config.OPENAI_TPM_LIMIT,
        run_token_cap=config.OPENAI_RUN_TOKEN_CAP,
    )

    total = len(to_process)
    successes = 0
    failures = 0
    skipped = 0

    print(f"\nSummarizing {total} staged episode(s) via OpenAI [{config.OPENAI_MODEL}]")
    print(f"  RPM limit : {config.OPENAI_RPM_LIMIT or 'none'}")
    print(f"  TPM limit : {config.OPENAI_TPM_LIMIT or 'none'}")
    print(f"  Token cap : {config.OPENAI_RUN_TOKEN_CAP or 'none'}")
    print(f"  Req delay : {config.OPENAI_REQUEST_DELAY}s\n")

    for idx, ep_num in enumerate(to_process, start=1):
        transcript_file = STAGING_DIR / f"{ep_num}_transcript.txt"
        if not transcript_file.exists():
            skipped += 1
            print(f"  ⏭  [{idx}/{total}] #{ep_num} — transcript missing, skipping")
            continue

        try:
            ep, transcript = _load_staged_episode(ep_num)
        except Exception as exc:
            failures += 1
            print(f"  ❌ [{idx}/{total}] #{ep_num} — failed to load staged files: {exc}")
            continue

        print(f"  🤖 [{idx}/{total}] #{ep_num} — {ep.guest or ep.title} …", end=" ", flush=True)

        try:
            notes_md = summarizer.generate_notes_with_limit(
                transcript,
                ep,
                limiter=limiter,
                request_delay=config.OPENAI_REQUEST_DELAY,
            )
        except RuntimeError as exc:
            failures += 1
            print(f"\n  ❌ [{idx}/{total}] #{ep_num} — {exc}")
            if "token cap" in str(exc).lower():
                print(f"\nRun token cap reached after {successes} episodes. Re-run to continue.")
                break
            continue
        except Exception as exc:
            failures += 1
            print(f"\n  ❌ [{idx}/{total}] #{ep_num} — OpenAI error: {exc}")
            continue

        try:
            filepath = writer.write_note(notes_md, ep.number, ep.guest, ep.title)
            tracker.mark_processed(ep.number, ep.guest, ep.title, ep.url, status="completed")
            successes += 1
            print(f"✅  → {filepath.name}  [{limiter.total_tokens_used:,} tokens used]")
        except Exception as exc:
            failures += 1
            print(f"\n  ❌ [{idx}/{total}] #{ep_num} — write failed: {exc}")

    print(f"\nDone. {successes} succeeded, {skipped} skipped, {failures} failed.")
    print(f"Total tokens consumed this run: {limiter.total_tokens_used:,}")


def cmd_rename_vault_range(args: argparse.Namespace) -> None:
    """Rename existing vault notes for an episode range to the current naming scheme."""
    start = args.start
    end = args.end
    if start > end:
        start, end = end, start

    vault_dir = config.output_dir()
    total = end - start + 1
    renamed = 0
    skipped = 0
    failures = 0

    for idx, ep_num in enumerate(range(start, end + 1), start=1):
        try:
            ep, _transcript = _load_staged_episode(ep_num)
        except Exception as exc:
            failures += 1
            print(f"  ❌ [{idx}/{total}] #{ep_num} — missing staged meta/transcript: {exc}")
            continue

        target_name = writer.build_filename(ep.number, ep.guest, ep.title)
        target_path = vault_dir / target_name

        # If already correct, nothing to do
        if target_path.exists() and not args.force:
            skipped += 1
            print(f"  ⏭  [{idx}/{total}] #{ep_num} — already named correctly")
            continue

        # Find existing legacy file(s)
        legacy_candidates = sorted(vault_dir.glob(f"Modern-Wisdom-{ep_num}-*.md"))
        if not legacy_candidates:
            skipped += 1
            print(f"  ⏭  [{idx}/{total}] #{ep_num} — no legacy file found")
            continue

        if len(legacy_candidates) > 1:
            failures += 1
            names = ", ".join(p.name for p in legacy_candidates[:3])
            extra = "" if len(legacy_candidates) <= 3 else f" (+{len(legacy_candidates) - 3} more)"
            print(f"  ❌ [{idx}/{total}] #{ep_num} — multiple legacy files found: {names}{extra}")
            continue

        legacy_path = legacy_candidates[0]

        if args.dry_run:
            print(f"  📝 [{idx}/{total}] #{ep_num} — would rename '{legacy_path.name}' -> '{target_path.name}'")
            continue

        try:
            if target_path.exists() and args.force:
                backup_path = target_path.with_suffix(target_path.suffix + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
                target_path.rename(backup_path)
            legacy_path.rename(target_path)
            renamed += 1
            print(f"  ✅ [{idx}/{total}] #{ep_num} — renamed to '{target_path.name}'")
        except Exception as exc:
            failures += 1
            print(f"  ❌ [{idx}/{total}] #{ep_num} — rename failed: {exc}")

    summary = f"\nDone. {renamed} renamed, {skipped} skipped, {failures} failed."
    if args.dry_run:
        summary += " (dry-run)"
    print(summary)
    print(f"Vault folder: {vault_dir.resolve()}")


def cmd_write_notes_range(args: argparse.Namespace) -> None:
    """Write staged notes (staging/{ep}_note.md) to the vault for a range."""
    start = args.start
    end = args.end

    if start > end:
        start, end = end, start

    total = end - start + 1
    successes = 0
    failures = 0
    skipped = 0

    for idx, ep_num in enumerate(range(start, end + 1), start=1):
        note_path = STAGING_DIR / f"{ep_num}_note.md"
        if not note_path.exists():
            skipped += 1
            print(f"  ⏭  [{idx}/{total}] #{ep_num} — missing staged note (expected {note_path.name})")
            continue

        try:
            ep, _transcript = _load_staged_episode(ep_num)
        except Exception as exc:
            failures += 1
            print(f"  ❌ [{idx}/{total}] #{ep_num} — missing staged meta/transcript: {exc}")
            continue

        try:
            notes_md = note_path.read_text(encoding="utf-8")
            filepath = writer.write_note(notes_md, ep.number, ep.guest, ep.title)
            tracker.mark_processed(ep.number, ep.guest, ep.title, ep.url, status="completed")
            successes += 1
            print(f"  ✅ [{idx}/{total}] #{ep.number} — wrote {filepath.name}")
        except Exception as exc:
            failures += 1
            print(f"  ❌ [{idx}/{total}] #{ep_num} — write failed: {exc}")

    print(f"\nDone. {successes} succeeded, {skipped} skipped, {failures} failed.")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Modern Wisdom Podcast → Obsidian Notes pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = sub.add_parser("list", help="Show available episodes and status")
    p_list.add_argument("--pages", type=int, default=10, help="Max listing pages to scrape")
    p_list.set_defaults(func=cmd_list)

    # process
    p_proc = sub.add_parser("process", help="Process a single episode")
    p_proc.add_argument("--episode", "-e", type=int, required=True, help="Episode number")
    p_proc.add_argument("--force", "-f", action="store_true", help="Re-process even if already done")
    p_proc.add_argument("--pages", type=int, default=10)
    p_proc.set_defaults(func=cmd_process)

    # process-latest
    p_latest = sub.add_parser("process-latest", help="Process latest N unprocessed episodes")
    p_latest.add_argument("--count", "-n", type=int, default=5, help="Number of episodes")
    p_latest.add_argument("--pages", type=int, default=10)
    p_latest.set_defaults(func=cmd_process_latest)

    # process-all
    p_all = sub.add_parser("process-all", help="Process all unprocessed episodes")
    p_all.add_argument("--pages", type=int, default=50)
    p_all.set_defaults(func=cmd_process_all)

    # status
    p_status = sub.add_parser("status", help="Show tracker status")
    p_status.set_defaults(func=cmd_status)

    # scrape  (single episode)
    p_scrape = sub.add_parser("scrape", help="Scrape one transcript to staging/")
    p_scrape.add_argument("--episode", "-e", type=int, required=True, help="Episode number")
    p_scrape.add_argument("--force", "-f", action="store_true", help="Re-scrape even if already done")
    p_scrape.add_argument("--pages", type=int, default=10)
    p_scrape.set_defaults(func=cmd_scrape)

    # scrape-latest  (batch)
    p_sl = sub.add_parser("scrape-latest", help="Batch scrape latest N unscraped transcripts")
    p_sl.add_argument("--count", "-n", type=int, default=10, help="Number of episodes (default 10)")
    p_sl.add_argument("--delay", "-d", type=float, default=scraper.DEFAULT_SCRAPE_DELAY,
                       help=f"Seconds between page loads (default {scraper.DEFAULT_SCRAPE_DELAY})")
    p_sl.add_argument("--pages", type=int, default=200, help="Max listing pages to scan")
    p_sl.set_defaults(func=cmd_scrape_latest)

    # scrape-all  (batch — full catalog)
    p_sa = sub.add_parser("scrape-all", help="Batch scrape ALL unscraped transcripts")
    p_sa.add_argument("--delay", "-d", type=float, default=scraper.DEFAULT_SCRAPE_DELAY,
                       help=f"Seconds between page loads (default {scraper.DEFAULT_SCRAPE_DELAY})")
    p_sa.add_argument("--force", "-f", action="store_true", help="Re-scrape everything")
    p_sa.add_argument("--pages", type=int, default=200, help="Max listing pages to scan")
    p_sa.set_defaults(func=cmd_scrape_all)

    # generate-processed  (LLM fills in episode template from staged transcript)
    p_gp = sub.add_parser(
        "generate-processed",
        help="Generate episode notes into processed/ from staging/ using the episode template",
    )
    p_gp.add_argument(
        "--episode",
        "-e",
        type=int,
        default=None,
        help="Generate for a single episode number (default: all staged)",
    )
    p_gp.add_argument(
        "--delay",
        "-d",
        type=float,
        default=0,
        help="Optional delay (seconds) between LLM calls",
    )
    p_gp.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Overwrite already-generated processed notes",
    )
    p_gp.set_defaults(func=cmd_generate_processed)

    # write-notes-range  (Option A Step 3 helper)
    p_wnr = sub.add_parser(
        "write-notes-range",
        help="Write staging/{ep}_note.md to the vault for a numeric episode range",
    )
    p_wnr.add_argument("--start", type=int, required=True, help="Start episode number")
    p_wnr.add_argument("--end", type=int, required=True, help="End episode number")
    p_wnr.set_defaults(func=cmd_write_notes_range)

    # rename-vault-range  (rename legacy vault notes to current naming)
    p_rvr = sub.add_parser(
        "rename-vault-range",
        help="Rename vault notes for a numeric episode range to 'Modern Wisdom - {episode} - {guest}.md'",
    )
    p_rvr.add_argument("--start", type=int, required=True, help="Start episode number")
    p_rvr.add_argument("--end", type=int, required=True, help="End episode number")
    p_rvr.add_argument("--dry-run", action="store_true", help="Show what would be renamed without changing files")
    p_rvr.add_argument("--force", "-f", action="store_true", help="If target exists, move it aside to a .bak and rename")
    p_rvr.set_defaults(func=cmd_rename_vault_range)

    # summarize-staged  (Option B batch — skip scraping, only OpenAI + vault)
    p_ss = sub.add_parser(
        "summarize-staged",
        help="Batch summarize all staged transcripts via OpenAI and write to vault (no scraping)",
    )
    p_ss.add_argument(
        "--episode", "-e", type=int, default=None,
        help="Process a single episode number (default: all staged not yet processed)",
    )
    p_ss.add_argument(
        "--force", "-f", action="store_true",
        help="Re-process episodes already marked completed in the tracker",
    )
    p_ss.set_defaults(func=cmd_summarize_staged)

    # write-note  (post-Cascade step)
    p_write = sub.add_parser("write-note", help="Write a pre-generated note to vault + tracker")
    p_write.add_argument("--episode", "-e", type=int, required=True, help="Episode number")
    p_write.add_argument("--file", required=True, help="Path to the generated markdown note")
    p_write.set_defaults(func=cmd_write_note)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
