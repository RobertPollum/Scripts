"""Deep YTS diagnostics - test API directly, check logs, find alternative mirrors."""
import urllib.request, json, urllib.error, ssl
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR = f"http://{_env_prowlarr_ip}:9696"
PROWLARR_KEY = os.environ["PROWLARR_API_KEY"]

def prowlarr_get(path):
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, headers={"X-Api-Key": PROWLARR_KEY})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

# Test the YTS API URL directly from this machine
print("=== Testing YTS API endpoints directly ===")
yts_urls = [
    "https://movies-api.accel.li/api/v2/list_movies.json?limit=5",
    "https://yts.mx/api/v2/list_movies.json?limit=5",
    "https://yts.lt/api/v2/list_movies.json?limit=5",
]
for url in yts_urls:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            status = data.get("status", "?")
            count = data.get("data", {}).get("movie_count", "?")
            print(f"  {url.split('/')[2]}: OK status={status} movies={count}")
    except urllib.error.HTTPError as e:
        print(f"  {url.split('/')[2]}: HTTP {e.code}")
    except Exception as e:
        print(f"  {url.split('/')[2]}: FAIL - {type(e).__name__}: {str(e)[:80]}")

# Test via Prowlarr's proxy (how Radarr actually hits it)
print()
print("=== Testing YTS through Prowlarr Torznab proxy ===")
# YTS indexer id=8
for label, url in [
    ("caps", f"{PROWLARR}/8/api?t=caps&apikey={PROWLARR_KEY}"),
    ("movie search", f"{PROWLARR}/8/api?t=movie&q=iron+man&apikey={PROWLARR_KEY}"),
]:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
            print(f"  {label}: OK ({len(data)} bytes)")
            if label == "movie search":
                # Count results
                import xml.etree.ElementTree as ET
                try:
                    root = ET.fromstring(data)
                    items = root.findall(".//item")
                    print(f"    Results: {len(items)} torrents found")
                except:
                    pass
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        print(f"  {label}: HTTP {e.code} - {body}")
    except Exception as e:
        print(f"  {label}: FAIL - {type(e).__name__}: {str(e)[:100]}")

# Check all recent warn+error logs mentioning YTS or accel.li
print()
print("=== Prowlarr warn logs (last 100, YTS-related) ===")
for level in ["warn", "error"]:
    logs = prowlarr_get(f"log?level={level}&pageSize=100&sortKey=time&sortDir=desc")
    for rec in logs.get("records", []):
        msg = rec.get("message", "")
        if any(x in msg.lower() for x in ["yts", "accel.li", "id=8", "indexerid=8"]):
            print(f"  [{level}][{rec.get('time','')[:19]}] {msg[:150]}")

# Show current YTS indexer full config
print()
print("=== Full YTS indexer fields ===")
idxs = prowlarr_get("indexer")
yts = next((i for i in idxs if i["name"] == "YTS"), None)
if yts:
    for f in yts.get("fields", []):
        if f.get("value") is not None and f["value"] != "" and f["value"] != []:
            print(f"  {f['name']} = {f['value']}")
