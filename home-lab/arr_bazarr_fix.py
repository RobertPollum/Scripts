"""Debug Bazarr settings persistence - find why apikey doesn't save."""
import requests, json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BAZARR_IP  = os.environ["BAZARR_IP"]
BAZARR_KEY = os.environ["BAZARR_API_KEY"]
SONARR_IP  = os.environ["SONARR_IP"]
SONARR_KEY = os.environ["SONARR_API_KEY"]
RADARR_IP  = os.environ["RADARR_IP"]
RADARR_KEY = os.environ["RADARR_API_KEY"]
BASE = f"http://{BAZARR_IP}:6767"
HDRS = {"X-Api-Key": BAZARR_KEY, "Content-Type": "application/json"}

# 1. See full sonarr section from settings GET
full = requests.get(f"{BASE}/api/system/settings", headers=HDRS).json()
print("=== Current sonarr section (all keys) ===")
print(json.dumps(full.get("sonarr", {}), indent=2))

print("\n=== Current radarr section ===")
print(json.dumps(full.get("radarr", {}), indent=2))

# 2. Try POSTing just the sonarr section with apikey (not apikey)
# Check if Bazarr uses 'apikey' or 'api_key' or something else
print("\n=== Testing minimal sonarr POST ===")
payload = {
    "sonarr": {
        "ip": SONARR_IP,
        "port": 8989,
        "apikey": SONARR_KEY,
        "ssl": False,
        "base_url": "/",
    }
}
r = requests.post(f"{BASE}/api/system/settings", headers=HDRS, data=json.dumps(payload))
print(f"POST: {r.status_code}")

# Verify
verify = requests.get(f"{BASE}/api/system/settings", headers=HDRS).json()
print(f"After POST sonarr.ip: {verify['sonarr']['ip']}")
print(f"After POST sonarr.apikey: {repr(verify['sonarr'].get('apikey',''))}")

# 3. Maybe Bazarr validates the connection and rejects bad apikey?
# Try with use_sonarr: True and check if there's a test endpoint
print("\n=== Bazarr API endpoints ===")
for ep in ["/api/system/tests", "/api/providers", "/api/system/status"]:
    r2 = requests.get(f"{BASE}{ep}", headers=HDRS)
    print(f"  {ep}: {r2.status_code}")
