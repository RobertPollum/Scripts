"""Diagnose why Radarr indexers are failing."""
import urllib.request, json, urllib.error
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

_env_radarr_ip = os.environ["RADARR_IP"]
RADARR = f"http://{_env_radarr_ip}:7878"
RADARR_KEY = os.environ["RADARR_API_KEY"]
_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR = f"http://{_env_prowlarr_ip}:9696"
PROWLARR_KEY = os.environ["PROWLARR_API_KEY"]

def radarr_get(path):
    req = urllib.request.Request(RADARR + "/api/v3/" + path, headers={"X-Api-Key": RADARR_KEY})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def radarr_post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(RADARR + "/api/v3/" + path, data=body,
                                  headers={"X-Api-Key": RADARR_KEY, "Content-Type": "application/json"})
    req.get_method = lambda: "POST"
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"{e.code}: {e.read().decode()[:300]}"

# Get each indexer's Torznab URL and test it
print("=== RADARR INDEXER TORZNAB TESTS ===")
idxs = radarr_get("indexer")
for i in idxs:
    name = i["name"]
    base_url = next((f["value"] for f in i.get("fields", []) if f["name"] == "baseUrl" and "value" in f), None)
    print(f"\n{name}")
    print(f"  baseUrl: {base_url}")
    if base_url:
        # Test caps
        url = base_url.rstrip("/") + "/api?t=caps&apikey=" + PROWLARR_KEY
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read()
                print(f"  caps: OK ({len(data)} bytes)")
        except Exception as e:
            print(f"  caps: FAIL - {e}")
        # Test movie search
        url2 = base_url.rstrip("/") + "/api?t=movie&q=iron+man&cat=2000&apikey=" + PROWLARR_KEY
        try:
            req = urllib.request.Request(url2)
            with urllib.request.urlopen(req, timeout=15) as r:
                data = r.read()
                print(f"  movie search: OK ({len(data)} bytes)")
        except Exception as e:
            print(f"  movie search: FAIL - {e}")

# Test indexers via Radarr's own test endpoint
print()
print("=== RADARR INDEXER TEST (via Radarr API) ===")
for i in idxs:
    result, err = radarr_post("indexer/test", i)
    if err:
        print(f"  {i['name']}: FAIL - {err[:150]}")
    else:
        print(f"  {i['name']}: OK")

# Check Radarr's indexer status/backoff table
print()
print("=== RADARR SYSTEM TASKS ===")
try:
    tasks = radarr_get("system/task")
    for t in tasks:
        if "indexer" in t.get("name","").lower() or "rss" in t.get("name","").lower():
            print(f"  {t['name']} lastExecution={str(t.get('lastExecution','?'))[:19]} nextExecution={str(t.get('nextExecution','?'))[:19]}")
except Exception as e:
    print(f"  ERROR: {e}")
