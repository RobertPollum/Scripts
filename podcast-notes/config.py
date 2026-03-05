import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the same directory as this file
_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)

# ---------------------------------------------------------------------------
# OpenAI / LLM
# ---------------------------------------------------------------------------
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

# ---------------------------------------------------------------------------
# Obsidian vault
# ---------------------------------------------------------------------------
OBSIDIAN_VAULT_PATH: str = os.getenv("OBSIDIAN_VAULT_PATH", "C:/Users/rober/Robert-Vault")
OBSIDIAN_SUBFOLDER: str = os.getenv("OBSIDIAN_SUBFOLDER", "Podcasts")

# ---------------------------------------------------------------------------
# Podscripts
# ---------------------------------------------------------------------------
PODSCRIPTS_BASE_URL: str = os.getenv(
    "PODSCRIPTS_BASE_URL",
    "https://podscripts.co/podcasts/modern-wisdom",
)

# ---------------------------------------------------------------------------
# Tracker file (lives next to this script)
# ---------------------------------------------------------------------------
TRACKER_PATH: str = str(Path(__file__).parent / "processed_episodes.csv")

# ---------------------------------------------------------------------------
# Derived helpers
# ---------------------------------------------------------------------------
def output_dir() -> Path:
    """Return the full path to the Obsidian output folder, creating it if needed."""
    p = Path(OBSIDIAN_VAULT_PATH) / OBSIDIAN_SUBFOLDER
    p.mkdir(parents=True, exist_ok=True)
    return p
