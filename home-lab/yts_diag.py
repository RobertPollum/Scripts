"""Diagnose YTS indexer failures in Prowlarr and find a fix."""
import urllib.request, json, urllib.error
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

# Get YTS indexer config
print("=== YTS Indexer Config ===")
idxs = get("indexer")
yts = next((i for i in idxs if i["name"] == "YTS"), None)
if not yts:
    print("YTS not found!")
else:
    print(f"  id={yts['id']} enable={yts.get('enable')} tags={yts.get('tags')}")
    fields = {f["name"]: f.get("value") for f in yts.get("fields", []) if "value" in f}
    for k, v in fields.items():
        print(f"  {k} = {v}")

# Check backoff status
print()
print("=== Prowlarr Indexer Backoff ===")
statuses = get("indexerstatus")
yts_status = next((s for s in statuses if s.get("indexerId") == yts["id"]), None) if yts else None
if yts_status:
    print(f"  YTS: disabledTill={yts_status.get('disabledTill')} escalationLevel={yts_status.get('escalationLevel')}")
else:
    print("  YTS: no backoff entry currently")

# Test YTS Torznab endpoint directly
print()
print("=== Direct YTS Torznab Test ===")
if yts:
    fields = {f["name"]: f.get("value") for f in yts.get("fields", []) if "value" in f}
    base_url = fields.get("baseUrl", "")
    if base_url:
        for label, params in [
            ("caps", f"?t=caps&apikey={PROWLARR_KEY}"),
            ("movie search", f"?t=movie&q=iron+man&cat=2000&apikey={PROWLARR_KEY}"),
        ]:
            url = base_url.rstrip("/") + "/api" + params
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = r.read()
                    print(f"  {label}: OK ({len(data)} bytes)")
            except urllib.error.HTTPError as e:
                print(f"  {label}: HTTP {e.code} - {e.read().decode()[:200]}")
            except Exception as e:
                print(f"  {label}: FAIL - {e}")

# Check recent Prowlarr error logs for YTS
print()
print("=== Recent YTS Error Logs ===")
logs = get("log?level=error&pageSize=50&sortKey=time&sortDir=desc")
yts_logs = [r for r in logs.get("records", []) if "yts" in r.get("message", "").lower() or "YTS" in r.get("message", "")]
for rec in yts_logs[:10]:
    print(f"  [{rec.get('time','')[:19]}] {rec.get('message','')[:120]}")

# Check YTS alternative URLs / mirrors
print()
print("=== YTS indexer definition ===")
if yts:
    fields = {f["name"]: f.get("value") for f in yts.get("fields", []) if "value" in f}
    print(f"  baseUrl: {fields.get('baseUrl')}")
    print(f"  definitionFile: {fields.get('definitionFile')}")
