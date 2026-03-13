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
OBSIDIAN_VAULT_PATH: str = os.getenv("OBSIDIAN_VAULT_PATH", "C:/Users/rober/OneDrive/Documents/Notes/Obsidian/")
OBSIDIAN_SUBFOLDER: str = os.getenv("OBSIDIAN_SUBFOLDER", "Robert-Vault/Podcasts/Modern Wisdom")

# ---------------------------------------------------------------------------
# Podscripts
# ---------------------------------------------------------------------------
PODSCRIPTS_BASE_URL: str = os.getenv(
    "PODSCRIPTS_BASE_URL",
    "https://podscripts.co/podcasts/modern-wisdom",
)

# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------
# Admin API key (separate from OPENAI_API_KEY) — required to query the Costs API.
# Generate one at: https://platform.openai.com/settings/organization/admin-keys
OPENAI_ADMIN_KEY: str = os.getenv("OPENAI_ADMIN_KEY", "")
# Monthly spend ceiling in USD (0 = no budget check performed)
OPENAI_MONTHLY_BUDGET_USD: float = float(os.getenv("OPENAI_MONTHLY_BUDGET_USD", "0"))

# ---------------------------------------------------------------------------
# Rate limiting (Option B batch mode)
# ---------------------------------------------------------------------------
# Requests per minute ceiling (0 = no limit enforced)
OPENAI_RPM_LIMIT: int = int(os.getenv("OPENAI_RPM_LIMIT", "500"))
# Tokens per minute ceiling (0 = no limit enforced)
OPENAI_TPM_LIMIT: int = int(os.getenv("OPENAI_TPM_LIMIT", "200000"))
# Max tokens consumed in a single run (0 = no limit enforced)
OPENAI_RUN_TOKEN_CAP: int = int(os.getenv("OPENAI_RUN_TOKEN_CAP", "0"))
# Seconds to sleep between API calls when no other throttle applies
OPENAI_REQUEST_DELAY: float = float(os.getenv("OPENAI_REQUEST_DELAY", "0.5"))

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
