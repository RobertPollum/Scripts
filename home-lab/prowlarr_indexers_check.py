"""Check current Prowlarr indexers and available private/semi-private ones."""
import urllib.request, json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR = f"http://{_env_prowlarr_ip}:9696"
PROWLARR_KEY = os.environ["PROWLARR_API_KEY"]

def get(path):
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, headers={"X-Api-Key": PROWLARR_KEY})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

# Current indexers
print("=== Current Prowlarr Indexers ===")
idxs = get("indexer")
for i in sorted(idxs, key=lambda x: x["name"]):
    enabled = "ON " if i.get("enable") else "OFF"
    priv = i.get("privacy", "?")
    tags = i.get("tags", [])
    print(f"  [{enabled}] {i['name']:<30} privacy={priv}  tags={tags}")

print(f"\n  Total: {len(idxs)}")

# Current backoff status
print()
print("=== Indexer Backoff Status ===")
statuses = get("indexerstatus")
if statuses:
    for s in statuses:
        idx = next((i for i in idxs if i["id"] == s.get("indexerId")), {})
        print(f"  {idx.get('name','?')} disabledTill={s.get('disabledTill','?')[:19]}")
else:
    print("  No backoff entries ✓")

# Available indexer catalog - search for private ones
print()
print("=== Available Private/Semi-Private Indexers (catalog) ===")
catalog = get("indexer/schema")
private = [i for i in catalog if i.get("privacy") in ("private", "semiPrivate")]
semi = [i for i in catalog if i.get("privacy") == "semiPrivate"]
prv = [i for i in catalog if i.get("privacy") == "private"]

print(f"  Semi-private available: {len(semi)}")
print(f"  Private available: {len(prv)}")
print()
print("  Semi-private indexers:")
for i in sorted(semi, key=lambda x: x["name"]):
    cats = [c.get("name") for c in i.get("capabilities", {}).get("categories", [])[:3]]
    print(f"    {i['name']:<35} cats={cats[:2]}")

print()
print("  Private indexers (sample - top 30):")
for i in sorted(prv, key=lambda x: x["name"])[:30]:
    print(f"    {i['name']}")
