"""Check and fix FlareSolverr tag assignment for Cloudflare-protected indexers."""
import urllib.request, json, urllib.error
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR = f"http://{_env_prowlarr_ip}:9696"
KEY = os.environ["PROWLARR_API_KEY"]

def get(path):
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, headers={"X-Api-Key": KEY})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def put(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, data=body,
                                  headers={"X-Api-Key": KEY, "Content-Type": "application/json"})
    req.get_method = lambda: "PUT"
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"{e.code}: {e.read().decode()[:200]}"

# Get current state
indexers = get("indexer")
proxies = get("indexerProxy")
tags = get("tag")

print("=== Indexer proxies ===")
for p in proxies:
    print(f"  id={p['id']} name={p['name']} impl={p.get('implementationName')}")
    for f in p.get("fields", []):
        if f["name"] in ("host", "port") and f.get("value"):
            print(f"    {f['name']}={f['value']}")

print()
print("=== Current tags ===")
for t in tags:
    print(f"  id={t['id']} label={t['label']}")

# Find FlareSolverr proxy id
flare_proxy = next((p for p in proxies if "flare" in p.get("implementationName","").lower()), None)
print()
if not flare_proxy:
    print("ERROR: No FlareSolverr proxy found in Prowlarr!")
else:
    print(f"FlareSolverr proxy id={flare_proxy['id']}")

print()
print("=== All indexers + their proxy/tag assignments ===")
for idx in sorted(indexers, key=lambda x: x["name"]):
    proxy_id = idx.get("indexerProxyId") or idx.get("proxyId")
    itags = idx.get("tags", [])
    enabled = "ON " if idx.get("enable") else "OFF"
    print(f"  [{enabled}] {idx['name']:<35} proxyId={proxy_id}  tags={itags}")

# Cloudflare-protected indexers that need FlareSolverr
CF_INDEXERS = {"eztv", "1337x", "kickasstorrents", "torrentgalaxy", "torrentgalaxyclone"}

print()
print("=== Fixing CF indexers - assigning FlareSolverr proxy ===")
if not flare_proxy:
    print("  Skipped - no FlareSolverr proxy configured")
else:
    for idx in indexers:
        name_lower = idx["name"].lower()
        if any(cf in name_lower for cf in CF_INDEXERS):
            current_proxy = idx.get("indexerProxyId") or idx.get("proxyId")
            if current_proxy == flare_proxy["id"]:
                print(f"  {idx['name']}: already has FlareSolverr ✓")
                continue
            
            # Assign FlareSolverr proxy
            updated = dict(idx)
            # Try both field names
            updated["indexerProxyId"] = flare_proxy["id"]
            updated["proxyId"] = flare_proxy["id"]
            
            result, err = put(f"indexer/{idx['id']}", updated)
            if err:
                print(f"  {idx['name']}: PUT error - {err[:100]}")
            else:
                new_proxy = result.get("indexerProxyId") or result.get("proxyId")
                print(f"  {idx['name']}: assigned FlareSolverr (proxyId={new_proxy}) ✓")

print()
print("=== Post-fix indexer proxy state ===")
indexers2 = get("indexer")
for idx in sorted(indexers2, key=lambda x: x["name"]):
    proxy_id = idx.get("indexerProxyId") or idx.get("proxyId")
    enabled = "ON " if idx.get("enable") else "OFF"
    name_lower = idx["name"].lower()
    if any(cf in name_lower for cf in CF_INDEXERS):
        status = "✓" if proxy_id else "✗ NO PROXY"
        print(f"  [{enabled}] {idx['name']:<35} proxyId={proxy_id} {status}")
