import requests
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
base = f"http://{_env_prowlarr_ip}:9696"
key = os.environ["PROWLARR_API_KEY"]
headers = {'X-Api-Key': key}

# Get all indexers
r = requests.get(f'{base}/api/v1/indexer', headers=headers)
indexers = r.json()
print('=== INDEXERS ===')
for ix in indexers:
    print(f"ID:{ix['id']} | {ix['name']} | Enable:{ix['enable']} | Tags:{ix.get('tags',[])}")

print()

# Get indexer status (errors/disabled)
r2 = requests.get(f'{base}/api/v1/indexerstatus', headers=headers)
statuses = r2.json()
print('=== INDEXER STATUSES (errors) ===')
# Build indexer id->name map
id_map = {ix['id']: ix['name'] for ix in indexers}
for s in statuses:
    name = id_map.get(s.get('indexerId'), 'Unknown')
    print(f"  [{name}] indexerId:{s.get('indexerId')} | disabledTill:{s.get('disabledTill')} | initialFailure:{s.get('initialFailure')} | mostRecentFailure:{s.get('mostRecentFailure')} | failureCount:{s.get('escalationLevel')}")
    if s.get('mostRecentFailure'):
        pass

print()

# Get recent logs filtered for errors/warn - unique messages
r3 = requests.get(f'{base}/api/v1/log', headers=headers, params={'level': 'error', 'pageSize': 100, 'sortKey': 'time', 'sortDir': 'desc'})
logs = r3.json()
print('=== RECENT ERROR LOGS ===')
records = logs.get('records', [])
seen = set()
for rec in records:
    msg = rec.get('message', '')
    logger = rec.get('logger', '')
    key_str = f"{logger}|{msg[:80]}"
    if key_str in seen:
        continue
    seen.add(key_str)
    print(f"[{rec.get('time','')}] {logger} | {msg}")
    if rec.get('exception'):
        # Print first line of exception only
        exc_lines = rec['exception'].strip().splitlines()
        print(f"  EXCEPTION: {exc_lines[0]}")

print()

# Also get warning logs for CloudFlare/FlareSolverr mentions
r4 = requests.get(f'{base}/api/v1/log', headers=headers, params={'level': 'warn', 'pageSize': 50, 'sortKey': 'time', 'sortDir': 'desc'})
wlogs = r4.json()
print('=== RECENT WARN LOGS ===')
wrecords = wlogs.get('records', [])
for rec in wrecords[:15]:
    print(f"[{rec.get('time','')}] {rec.get('logger','')} | {rec.get('message','')}")
