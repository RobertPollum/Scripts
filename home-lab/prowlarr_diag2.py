import requests
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
base = f"http://{_env_prowlarr_ip}:9696"
api_key = os.environ["PROWLARR_API_KEY"]
headers = {'X-Api-Key': api_key}

# Get all indexers
r = requests.get(f'{base}/api/v1/indexer', headers=headers)
indexers = r.json()
id_map = {ix['id']: ix['name'] for ix in indexers}

print('=== ALL INDEXERS ===')
for ix in indexers:
    print(f"  ID:{ix['id']} | {ix['name']} | Enable:{ix['enable']} | Tags:{ix.get('tags',[])}")

print()

# Get indexer status (disabled/failing)
r2 = requests.get(f'{base}/api/v1/indexerstatus', headers=headers)
statuses = r2.json()
print(f'=== INDEXER STATUSES ({len(statuses)} with errors) ===')
for s in statuses:
    name = id_map.get(s.get('indexerId'), 'Unknown')
    print(f"  [{name}] disabledTill:{s.get('disabledTill')} | initialFailure:{s.get('initialFailure')} | mostRecentFailure:{s.get('mostRecentFailure')}")

print()

# FlareSolverr proxy check
r5 = requests.get(f'{base}/api/v1/indexerproxy', headers=headers)
proxies = r5.json()
print('=== INDEXER PROXIES (FlareSolverr etc) ===')
for p in proxies:
    print(f"  ID:{p['id']} | {p['name']} | Tags:{p.get('tags',[])}")
    for field in p.get('fields', []):
        if field.get('name') in ('host', 'port', 'requestTimeout'):
            print(f"    {field['name']}: {field.get('value')}")

print()

# Test FlareSolverr connectivity from LXC perspective - check if any CF indexers have the proxy tag
print('=== CF INDEXERS vs PROXY TAGS ===')
proxy_tags = set()
for p in proxies:
    proxy_tags.update(p.get('tags', []))

for ix in indexers:
    tags = ix.get('tags', [])
    has_proxy_tag = any(t in proxy_tags for t in tags)
    print(f"  [{ix['name']}] tags:{tags} | has_proxy_tag:{has_proxy_tag}")

print()

# Check DNS resolution issue - look at which indexers are DNS failing vs CF blocking
print('=== DNS-FAILING INDEXERS ===')
dns_fail_names = ['torrentgalaxy', 'uindex', '1337x', 'kickass', 'torrentdownloads', 'eztv']
for ix in indexers:
    name_lower = ix['name'].lower()
    if any(d in name_lower for d in dns_fail_names):
        in_status = any(s['indexerId'] == ix['id'] for s in statuses)
        print(f"  [{ix['name']}] id:{ix['id']} | disabled:{in_status}")
