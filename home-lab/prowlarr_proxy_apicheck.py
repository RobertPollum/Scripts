"""Check exact API response fields for an indexer to find where proxy is stored."""
import urllib.request, json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR = f"http://{_env_prowlarr_ip}:9696"
KEY = os.environ["PROWLARR_API_KEY"]

def get(path, timeout=15):
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, headers={"X-Api-Key": KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

# Dump the full raw JSON for 1337x
print("=== Full API response for 1337x (id=10) ===")
idx = get("indexer/10")
print(json.dumps(idx, indent=2))
