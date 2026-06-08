"""
Diagnose discrepancy between Radarr queue and Jellyseerr request statuses.
"""
import requests
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_env_radarr_ip = os.environ["RADARR_IP"]
RADARR_BASE = f"http://{_env_radarr_ip}:7878"
RADARR_KEY = os.environ["RADARR_API_KEY"]

_env_seerr_ip = os.environ["SEERR_IP"]
SEERR_BASE = f"http://{_env_seerr_ip}:5055"
# Jellyseerr uses cookie/session auth or API key - check if API key endpoint exists
# Common: X-Api-Key header or ?apikey= param

R_HEADERS = {'X-Api-Key': RADARR_KEY}

print("=== RADARR QUEUE ===")
r = requests.get(f'{RADARR_BASE}/api/v3/queue', headers=R_HEADERS, params={'pageSize': 100, 'includeMovie': True})
queue = r.json()
records = queue.get('records', [])
print(f"Total in Radarr queue: {queue.get('totalRecords', len(records))}")
for item in records:
    movie = item.get('movie', {})
    print(f"  [{item.get('status')}] {movie.get('title','?')} ({movie.get('year','?')}) | tmdbId:{movie.get('tmdbId','?')} | size:{item.get('size',0)//1024//1024}MB | protocol:{item.get('protocol')}")

print()
print("=== RADARR WANTED/MISSING ===")
r2 = requests.get(f'{RADARR_BASE}/api/v3/wanted/missing', headers=R_HEADERS, params={'pageSize': 20})
missing = r2.json()
print(f"Total missing: {missing.get('totalRecords', 0)}")
for m in missing.get('records', [])[:10]:
    print(f"  {m.get('title')} ({m.get('year')}) | tmdbId:{m.get('tmdbId')} | monitored:{m.get('monitored')}")

print()
print("=== JELLYSEERR API KEY CHECK ===")
# Try to get Jellyseerr settings to find API key
try:
    r3 = requests.get(f'{SEERR_BASE}/api/v1/settings/main', timeout=5)
    print(f"  /settings/main (no auth): {r3.status_code} {r3.text[:200]}")
except Exception as e:
    print(f"  Error: {e}")

# Try status endpoint (public)
try:
    r4 = requests.get(f'{SEERR_BASE}/api/v1/status', timeout=5)
    print(f"  /status: {r4.status_code} {r4.text[:200]}")
except Exception as e:
    print(f"  Error: {e}")
