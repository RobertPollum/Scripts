import re
import os
from pathlib import Path

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
_default_cache = _DOTENV.get("WINDSURF_CACHE_DIR")
if not _default_cache:
    raise SystemExit(
        "ERROR: WINDSURF_CACHE_DIR not set in .env.\n"
        "Create a .env file in the script directory with:\n"
        '  WINDSURF_CACHE_DIR=C:\\\\Users\\\\YOUR_NAME\\\\AppData\\\\Roaming\\\\Windsurf\\\\WebStorage\\\\...'
    )
cache_dir = Path(_default_cache)

UUID_RE = re.compile(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)

for f in sorted(cache_dir.iterdir()):
    if f.is_file() and not f.name.startswith('index'):
        data = f.read_bytes()
        # Print readable strings > 20 chars
        strings = re.findall(rb'[ -~]{20,}', data)
        uuids = UUID_RE.findall(data)
        if uuids or any(b'cascade' in s.lower() or b'conversation' in s.lower() or b'trajectory' in s.lower() for s in strings):
            print(f"\n=== {f.name} ({f.stat().st_size} bytes) ===")
            print(f"  UUIDs: {[u.decode() for u in uuids[:10]]}")
            for s in strings[:30]:
                print(f"  {s.decode(errors='replace')}")
