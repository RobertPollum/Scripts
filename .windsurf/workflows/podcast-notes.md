---
description: Generate Obsidian notes from Modern Wisdom podcast transcripts via podscripts.co
---

# Podcast Notes Workflow

Scrape Modern Wisdom podcast transcripts from podscripts.co, summarize with an LLM, and write structured Obsidian notes to `Robert-Vault/Podcasts`.

Two modes: **Windsurf Credits** (Cascade does the AI step) or **API Mode** (direct OpenAI call, needs API key).

## Prerequisites (one-time setup)

1. Ensure the venv and Playwright are installed:

```powershell
cd c:\Users\rober\workspace\Scripts\podcast-notes
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

2. Copy `.env.example` to `.env` and set `OBSIDIAN_VAULT_PATH` (required for both modes). Set `OPENAI_API_KEY` only if using API mode.

---

## Option A: Windsurf Credits (no API key needed)

This mode uses Cascade (your current Windsurf model) for the AI summarization step. No OpenAI API key required.

### Step 1 — Scrape the transcript

// turbo
3. Scrape the transcript for a specific episode number. Replace `<EPISODE_NUMBER>` with the desired number (e.g. `1066`):

```powershell
cd c:\Users\rober\workspace\Scripts\podcast-notes
.venv\Scripts\python main.py scrape --episode <EPISODE_NUMBER>
```

This saves two files to `podcast-notes/staging/`:
- `<number>_transcript.txt` — the raw transcript
- `<number>_meta.json` — episode metadata

### Step 2 — Cascade generates the note

4. Read the transcript and metadata that were just scraped:

Ask Cascade: "Read the transcript file at `c:\Users\rober\workspace\Scripts\podcast-notes\staging\<EPISODE_NUMBER>_transcript.txt` and the metadata at `c:\Users\rober\workspace\Scripts\podcast-notes\staging\<EPISODE_NUMBER>_meta.json`."

5. Then ask Cascade to generate the note using this prompt:

> Using the transcript and metadata you just read, generate an Obsidian note following the template in `c:\Users\rober\workspace\Scripts\podcast-notes\summarizer.py` (the SYSTEM_PROMPT). Write the result to `c:\Users\rober\workspace\Scripts\podcast-notes\staging\<EPISODE_NUMBER>_note.md`.

### Step 3 — Write note to vault

// turbo
6. Write the Cascade-generated note to the Obsidian vault:

```powershell
cd c:\Users\rober\workspace\Scripts\podcast-notes
.venv\Scripts\python main.py write-note --episode <EPISODE_NUMBER> --file staging\<EPISODE_NUMBER>_note.md
```
You don't have to ask to run the command, the above is safe to run and can be executed automatically as it's generative and accomplishing the task I want.
---

## Option B: API Mode (needs OPENAI_API_KEY in .env)

Fully automated — scrape, summarize via API, and write in one command.

### Batch summarize already-scraped transcripts (recommended when transcripts exist)

If transcripts are already in `staging/`, use this command to skip scraping and only run the OpenAI summarization + vault write step. This is the preferred path for bulk runs.

// turbo
7. Summarize all staged transcripts that haven't been processed yet:

```powershell
cd c:\Users\rober\workspace\Scripts\podcast-notes
.venv\Scripts\python main.py summarize-staged
```

Options:

```powershell
# One episode only
.venv\Scripts\python main.py summarize-staged --episode 1066

# Re-process already completed episodes
.venv\Scripts\python main.py summarize-staged --force
```

Rate limiting is controlled via `.env` (or environment variables):

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_RPM_LIMIT` | `500` | Max requests per minute (0 = no limit) |
| `OPENAI_TPM_LIMIT` | `200000` | Max tokens per minute (0 = no limit) |
| `OPENAI_RUN_TOKEN_CAP` | `0` | Hard token cap for the entire run (0 = unlimited) |
| `OPENAI_REQUEST_DELAY` | `0.5` | Minimum seconds between requests |

The command will auto-pause when approaching RPM/TPM limits and resume when the window clears. If `OPENAI_RUN_TOKEN_CAP` is hit, it stops cleanly and reports how many episodes completed; re-run to continue from where it left off (already processed episodes are skipped automatically).

### Process a specific episode (scrape + summarize + write in one step)

8. Process a single episode end-to-end:

```powershell
cd c:\Users\rober\workspace\Scripts\podcast-notes
.venv\Scripts\python main.py process --episode <EPISODE_NUMBER>
```

### Process latest unprocessed episodes

// turbo
9. Process the latest N unprocessed:

```powershell
cd c:\Users\rober\workspace\Scripts\podcast-notes
.venv\Scripts\python main.py process-latest --count 5
```

### Process all unprocessed episodes

10. Process everything (scrape + summarize + write):

```powershell
cd c:\Users\rober\workspace\Scripts\podcast-notes
.venv\Scripts\python main.py process-all
```

### Generate processed notes from staged transcripts (legacy)

If you already scraped a lot of episodes into `staging/` and want to generate episode notes in bulk using `templates/modern-wisdom-episode-template.md`, run:

```powershell
cd c:\Users\rober\workspace\Scripts\podcast-notes
.venv\Scripts\python main.py generate-processed
```

Options:

```powershell
# One episode
.venv\Scripts\python main.py generate-processed --episode 1066

# Delay between LLM calls (seconds)
.venv\Scripts\python main.py generate-processed --delay 2

# Overwrite existing files in processed/
.venv\Scripts\python main.py generate-processed --force
```

---

## Utility Commands

### List available episodes

// turbo
10. See available episodes and their processing status:

```powershell
cd c:\Users\rober\workspace\Scripts\podcast-notes
.venv\Scripts\python main.py list
```

### Check tracker status

// turbo
11. View which episodes have been completed or failed:

```powershell
cd c:\Users\rober\workspace\Scripts\podcast-notes
.venv\Scripts\python main.py status
```

## Output

- Notes → `Robert-Vault/Podcasts/Modern-Wisdom-1066-Dr-Kathryn-Paige-Harden-The-Genetics-of-Evil.md`
- Tracker → `podcast-notes/processed_episodes.csv`
- Staging files → `podcast-notes/staging/` (transcript + metadata + generated note)
- Re-process with `--force`: `python main.py process --episode 1066 --force`

## Troubleshooting

- **Transcript not found**: The page may require authentication on podscripts.co, or the transcript may not be available yet.
- **LLM errors (API mode)**: Verify `OPENAI_API_KEY` and `OPENAI_MODEL` in `.env`.
- **Playwright issues**: Run `playwright install chromium`.
