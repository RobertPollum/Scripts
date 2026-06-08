"""Switch YTS indexer apiurl from accel.li proxy to yts.mx directly."""
import urllib.request, json, urllib.error, time
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

def put(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, data=body,
                                  headers={"X-Api-Key": PROWLARR_KEY, "Content-Type": "application/json"})
    req.get_method = lambda: "PUT"
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"{e.code}: {e.read().decode()[:300]}"

def post(path, data=None):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, data=body,
                                  headers={"X-Api-Key": PROWLARR_KEY, "Content-Type": "application/json"})
    req.get_method = lambda: "POST"
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())

# First test which YTS mirror actually works FROM PROWLARR (CT110)
# We'll try updating to yts.mx and see if the test passes
idxs = get("indexer")
yts = next((i for i in idxs if i["name"] == "YTS"), None)
if not yts:
    print("ERROR: YTS indexer not found")
    exit(1)

print("=== Current YTS config ===")
for f in yts.get("fields", []):
    if f.get("value") not in (None, "", [], False):
        print(f"  {f['name']} = {f['value']}")

# Try candidate URLs in order
candidates = ["yts.mx", "yts.lt", "yts.do"]

for candidate in candidates:
    print(f"\n=== Testing apiurl = {candidate} ===")
    # Update the apiurl field
    updated = json.loads(json.dumps(yts))  # deep copy
    for f in updated["fields"]:
        if f["name"] == "apiurl":
            f["value"] = candidate
            break

    result, err = put(f"indexer/{yts['id']}", updated)
    if err:
        print(f"  PUT failed: {err[:150]}")
        continue

    print(f"  PUT OK - new apiurl = {candidate}")

    # Quick Torznab test
    time.sleep(2)
    test_url = f"{PROWLARR}/{yts['id']}/api?t=movie&q=iron+man&apikey={PROWLARR_KEY}"
    try:
        req = urllib.request.Request(test_url)
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
            import xml.etree.ElementTree as ET
            items = ET.fromstring(data).findall(".//item")
            print(f"  Torznab search: OK — {len(items)} results")
            print(f"  --> {candidate} WORKS, keeping this.")
            break
    except urllib.error.HTTPError as e:
        print(f"  Torznab search: HTTP {e.code} — trying next")
    except Exception as e:
        print(f"  Torznab search: {type(e).__name__}: {str(e)[:80]} — trying next")
else:
    print("\nAll candidates failed. Reverting to original accel.li.")
    for f in yts["fields"]:
        if f["name"] == "apiurl":
            f["value"] = "movies-api.accel.li"
            break
    put(f"indexer/{yts['id']}", yts)

# Final state
print()
print("=== Final YTS apiurl ===")
yts_final = get("indexer")
yts_f = next(i for i in yts_final if i["name"] == "YTS")
for f in yts_f.get("fields", []):
    if f["name"] == "apiurl":
        print(f"  apiurl = {f.get('value')}")

# Sync updated indexer to Radarr
print()
print("=== Syncing to Radarr ===")
r = post("command", {"name": "ApplicationIndexerSync", "applicationId": 1, "forceSync": True})
print(f"  Sync queued: id={r.get('id')}")
