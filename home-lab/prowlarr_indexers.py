"""
Add indexers to Prowlarr via API.
- Nyaa.si (anime, no CF)
- 1337x (general, needs FlareSolverr tag)
- YTS (movies, no CF typically)
- EZTV (TV shows)
- TorrentGalaxy (general, may need FlareSolverr)
- TheRARBG (RARBG mirror)
- Kickass Torrents (general)
"""
import requests, json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

PROWLARR_IP  = os.environ["PROWLARR_IP"]
PROWLARR_KEY = os.environ["PROWLARR_API_KEY"]

BASE = f"http://{PROWLARR_IP}:9696/api/v1"
HEADERS = {"X-Api-Key": PROWLARR_KEY, "Content-Type": "application/json"}

# ── Get existing indexers ─────────────────────────────────────────────────────
existing = requests.get(f"{BASE}/indexer", headers=HEADERS, timeout=10).json()
existing_names = [i.get("name","").lower() for i in existing]
print(f"Existing indexers: {[i.get('name') for i in existing]}")

# ── Get FlareSolverr proxy tag ID ─────────────────────────────────────────────
proxies = requests.get(f"{BASE}/indexerProxy", headers=HEADERS, timeout=10).json()
flare_proxy_id = None
for p in proxies:
    if "flaresolverr" in p.get("name","").lower():
        flare_proxy_id = p["id"]
print(f"FlareSolverr proxy id: {flare_proxy_id}")

# ── Get available indexer definitions ────────────────────────────────────────
print("\nFetching indexer catalog...")
schema = requests.get(f"{BASE}/indexer/schema", headers=HEADERS, timeout=15).json()
schema_by_name = {s.get("name","").lower(): s for s in schema}
print(f"Total available indexers: {len(schema)}")

# Indexers to add: (schema_name, needs_flaresolverr, enabled)
TO_ADD = [
    ("1337x",               True,  True),
    ("YTS",                 False, True),
    ("EZTV",               False, True),
    ("TorrentGalaxyClone",  True,  True),
    ("kickasstorrents.to",  True,  True),
    ("sukebei.nyaa.si",     False, True),   # adult anime — set False to skip
]

def add_indexer(name, use_flare):
    s = schema_by_name.get(name.lower())
    if not s:
        print(f"  ✗ '{name}' not found in schema")
        return False
    if name.lower() in existing_names:
        print(f"  ⏭  '{name}' already added")
        return True

    payload = dict(s)  # copy schema defaults
    payload["enable"] = True
    payload["priority"] = 25
    payload["appProfileId"] = 1
    # Attach FlareSolverr proxy via tags if needed
    if use_flare and flare_proxy_id:
        # Prowlarr uses indexerProxy field, not tags, to link proxy
        # The proxy applies to all indexers — just need to set the right tag
        # Actually Prowlarr links proxy to indexer via matching tags
        # Set a tag named 'flaresolverr' on both proxy and indexer
        # First ensure tag exists
        tags_resp = requests.get(f"{BASE}/tag", headers=HEADERS, timeout=10).json()
        flare_tag = next((t for t in tags_resp if t.get("label","").lower() == "flaresolverr"), None)
        if not flare_tag:
            r_tag = requests.post(f"{BASE}/tag",
                                  headers=HEADERS,
                                  data=json.dumps({"label": "flaresolverr"}),
                                  timeout=10)
            flare_tag = r_tag.json()
            print(f"  Created tag 'flaresolverr' id={flare_tag.get('id')}")
        payload["tags"] = [flare_tag["id"]]

    r = requests.post(f"{BASE}/indexer",
                      headers=HEADERS,
                      data=json.dumps(payload),
                      timeout=15)
    if r.status_code in (200, 201):
        flare_note = " [+FlareSolverr tag]" if use_flare else ""
        print(f"  ✅ '{name}' added (id={r.json().get('id')}){flare_note}")
        return True
    else:
        print(f"  ✗ '{name}' failed: {r.status_code} {r.text[:200]}")
        return False

# Also ensure FlareSolverr proxy itself has the matching tag
if flare_proxy_id:
    tags_resp = requests.get(f"{BASE}/tag", headers=HEADERS, timeout=10).json()
    flare_tag = next((t for t in tags_resp if t.get("label","").lower() == "flaresolverr"), None)
    if flare_tag:
        proxy_detail = requests.get(f"{BASE}/indexerProxy/{flare_proxy_id}",
                                    headers=HEADERS, timeout=10).json()
        if flare_tag["id"] not in proxy_detail.get("tags", []):
            proxy_detail["tags"] = list(set(proxy_detail.get("tags", []) + [flare_tag["id"]]))
            requests.put(f"{BASE}/indexerProxy/{flare_proxy_id}",
                         headers=HEADERS,
                         data=json.dumps(proxy_detail),
                         timeout=10)
            print(f"Updated FlareSolverr proxy with tag id={flare_tag['id']}")

print("\n=== Adding indexers ===")
for name, needs_flare, enabled in TO_ADD:
    if not enabled:
        print(f"  ⏭  '{name}' skipped (disabled)")
        continue
    add_indexer(name, needs_flare)

print("\n=== Final indexer list ===")
final = requests.get(f"{BASE}/indexer", headers=HEADERS, timeout=10).json()
for idx in final:
    tags = idx.get("tags", [])
    print(f"  {idx.get('name'):<30} enabled={idx.get('enable')}  tags={tags}")
