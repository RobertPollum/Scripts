"""
In Prowlarr, proxies are applied to indexers via TAGS - not a direct field.
If the FlareSolverr proxy has the same tag as the indexer, it gets used.
Check and fix: FlareSolverr proxy should have tag id=1 (flaresolverr).
"""
import urllib.request, json, urllib.error
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

def put(path, data, timeout=15):
    body = json.dumps(data).encode()
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, data=body,
                                  headers={"X-Api-Key": KEY, "Content-Type": "application/json"})
    req.get_method = lambda: "PUT"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:200]}"

# Get all the relevant objects
tags = get("tag")
proxies = get("indexerProxy")
indexers = get("indexer")

print("=== Tags ===")
for t in tags:
    print(f"  id={t['id']} label={t['label']}")

print()
print("=== FlareSolverr proxy (full) ===")
flare = next((p for p in proxies if "flare" in p.get("implementationName","").lower()), None)
print(json.dumps(flare, indent=2))

print()
print("=== Key finding ===")
flare_tags = flare.get("tags", []) if flare else []
print(f"  FlareSolverr proxy tags: {flare_tags}")
print(f"  Tag id=1 (flaresolverr) on proxy: {'YES' if 1 in flare_tags else 'NO - THIS IS THE BUG'}")

# The fix: assign tag id=1 to the FlareSolverr proxy
# Then all indexers that also have tag=1 will automatically use it
if flare and 1 not in flare_tags:
    print()
    print("=== Fix: Adding tag id=1 to FlareSolverr proxy ===")
    updated = dict(flare)
    updated["tags"] = list(set(flare_tags + [1]))
    result, err = put(f"indexerProxy/{flare['id']}", updated)
    if err:
        print(f"  PUT error: {err}")
    else:
        print(f"  Done. New tags: {result.get('tags')}")
elif flare:
    print()
    print("  FlareSolverr already has tag=1 — checking if indexers also have it")
    CF_NAMES = {"eztv", "1337x", "kickasstorrents", "torrentgalaxy"}
    for idx in indexers:
        if any(cf in idx["name"].lower() for cf in CF_NAMES):
            itags = idx.get("tags", [])
            print(f"  {idx['name']}: tags={itags} {'✓' if 1 in itags else '✗ MISSING TAG 1'}")

# Final state
print()
print("=== Final proxy + indexer tag state ===")
proxies2 = get("indexerProxy")
for p in proxies2:
    print(f"  Proxy '{p['name']}': tags={p.get('tags', [])}")

print()
CF_NAMES = {"eztv", "1337x", "kickasstorrents", "torrentgalaxy"}
indexers2 = get("indexer")
for idx in sorted(indexers2, key=lambda x: x["name"]):
    if any(cf in idx["name"].lower() for cf in CF_NAMES):
        itags = idx.get("tags", [])
        # Check if proxy tag matches
        proxy_match = any(t in itags for p in proxies2 for t in p.get("tags", []))
        mark = "✓" if proxy_match else "✗"
        print(f"  {mark} {idx['name']}: tags={itags}")
