import requests, json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
BASE = f"http://{_env_prowlarr_ip}:9696/api/v1"
H = {"X-Api-Key": os.environ["PROWLARR_API_KEY"]}

final = requests.get(f"{BASE}/indexer", headers=H, timeout=10).json()
print(f"Total indexers: {len(final)}")
for idx in final:
    tags = idx.get("tags", [])
    flare = " [FlareSolverr]" if 1 in tags else ""
    print(f"  {idx['name']:<35} enabled={idx['enable']}{flare}")
