# Modern Wisdom Podcast → Obsidian Notes

Automated pipeline that scrapes transcripts from [podscripts.co](https://podscripts.co/podcasts/modern-wisdom), sends them to an LLM for summarization, and writes structured Obsidian notes to your vault.

## Setup

```powershell
cd podcast-notes
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

Copy `.env.example` to `.env` and set `OBSIDIAN_VAULT_PATH`. Set `OPENAI_API_KEY` only if using API mode.

```powershell
copy .env.example .env
```

## Usage

### Batch Scraping (no API key needed)

Scrape transcripts to `staging/` for later summarization. Uses a single browser instance and rate-limits requests (default 8s between pages).

```powershell
# Scrape one episode
python main.py scrape --episode 1066

# Batch scrape the latest 10 unscraped episodes
python main.py scrape-latest --count 10

# Batch scrape the ENTIRE catalog
python main.py scrape-all

# Slower rate limit (12s) if you want to be extra polite
python main.py scrape-all --delay 12

# Force re-scrape everything
python main.py scrape-all --force
```

### Windsurf Credits Workflow (no API key needed)

After scraping, ask Cascade to generate the note from the staged transcript, then write it to the vault:

```powershell
python main.py write-note --episode 1066 --file staging/1066_note.md
```

### API Mode (needs OPENAI_API_KEY in .env)

Fully automated — scrape + AI summarization + vault write in one step:

```powershell
python main.py process --episode 1066
python main.py process-latest --count 5
python main.py process-all
```

### Generate `processed/` episode notes from `staging/` (needs OPENAI_API_KEY)

If you already scraped transcripts into `staging/` and want to generate notes in bulk using `templates/modern-wisdom-episode-template.md`:

```powershell
# Generate notes for every episode staged in staging/
python main.py generate-processed

# Generate one episode
python main.py generate-processed --episode 1066

# Add a small delay between LLM calls
python main.py generate-processed --delay 2

# Overwrite existing files in processed/
python main.py generate-processed --force
```

### Utility

```powershell
python main.py list      # available episodes & status
python main.py status    # tracker contents
```

## Configuration (.env)

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(API mode only)* | Your OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o` | Model to use for summarization |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API base URL (change for Azure, Ollama, etc.) |
| `OBSIDIAN_VAULT_PATH` | `C:/Users/rober/Robert-Vault` | Absolute path to your Obsidian vault |
| `OBSIDIAN_SUBFOLDER` | `Podcasts` | Subfolder within the vault for notes |
| `PODSCRIPTS_BASE_URL` | `https://podscripts.co/podcasts/modern-wisdom` | Podcast listing URL |

## Output

- **Notes** → `<OBSIDIAN_VAULT_PATH>/Podcasts/` with POSIX-compliant, OneDrive-safe filenames
- **Staged transcripts** → `staging/` (one `.txt` + one `_meta.json` per episode)
- **Processed notes** → `processed/` (generated notes prior to writing into the vault)
- **Tracker** → `processed_episodes.csv` (human-readable CSV)
- Filenames follow the pattern: `Modern-Wisdom-1066-Dr-Kathryn-Paige-Harden-The-Genetics-of-Evil.md`

## Architecture

| Module | Purpose |
|---|---|
| `config.py` | Configuration from `.env` with defaults |
| `scraper.py` | Scrape episode list + transcripts (Playwright for JS-rendered pages) |
| `summarizer.py` | LLM call with structured Obsidian template prompt |
| `tracker.py` | Human-readable CSV tracking of processed episodes |
| `writer.py` | POSIX/OneDrive-safe filename generation + vault writing |
| `main.py` | CLI entry point with subcommands |
