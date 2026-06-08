"""
Probe Jellyseerr auth methods to find one that works for /request endpoint.
The API key from settings.json may need to be used differently.
"""
import requests
import base64
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_env_seerr_ip = os.environ["SEERR_IP"]
SEERR_BASE = f"http://{_env_seerr_ip}:5055"
SEERR_KEY_B64 = os.environ["SEERR_API_KEY"]
SEERR_KEY = base64.b64decode(SEERR_KEY_B64).decode('utf-8')

# Try various auth header formats
attempts = [
    ('X-Api-Key header', {'X-Api-Key': SEERR_KEY}),
    ('Authorization Bearer', {'Authorization': f'Bearer {SEERR_KEY}'}),
    ('X-Api-Key raw b64', {'X-Api-Key': SEERR_KEY_B64}),
]

for label, headers in attempts:
    r = requests.get(f'{SEERR_BASE}/api/v1/request',
                     headers=headers,
                     params={'take': 5, 'filter': 'all'})
    print(f"[{label}] {r.status_code} {r.text[:120]}")

print()
# Try the /auth/local endpoint to get a session cookie
print("=== Trying session login ===")
# Default Jellyseerr admin creds — try common ones
for creds in [
    {'username': 'admin', 'password': 'admin'},
    {'username': 'admin', 'password': 'password'},
]:
    s = requests.Session()
    r = s.post(f'{SEERR_BASE}/api/v1/auth/local', json=creds)
    print(f"  Login {creds['username']}/{creds['password']}: {r.status_code} {r.text[:150]}")
    if r.status_code == 200:
        # Try request endpoint with session
        r2 = s.get(f'{SEERR_BASE}/api/v1/request', params={'take': 5, 'filter': 'all'})
        print(f"  /request with session: {r2.status_code} {r2.text[:200]}")
        break

print()
# Check if Jellyseerr has a user endpoint we can use to find admin user
r3 = requests.get(f'{SEERR_BASE}/api/v1/user', headers={'X-Api-Key': SEERR_KEY}, params={'take': 5})
print(f"GET /user: {r3.status_code} {r3.text[:300]}")

# Try /settings/main with the key
r4 = requests.get(f'{SEERR_BASE}/api/v1/settings/main', headers={'X-Api-Key': SEERR_KEY})
print(f"GET /settings/main: {r4.status_code} {r4.text[:300]}")
