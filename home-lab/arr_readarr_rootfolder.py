"""Set Readarr root folder — Readarr requires a 'name' field."""
import requests, json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

READARR_IP = os.environ["READARR_IP"]; READARR_KEY = os.environ["READARR_API_KEY"]

# Check schema first
r = requests.get(f"http://{READARR_IP}:8787/api/v1/rootfolder",
                 headers={"X-Api-Key": READARR_KEY}, timeout=10)
print("Existing:", r.json())

# POST with name field
r2 = requests.post(f"http://{READARR_IP}:8787/api/v1/rootfolder",
                   headers={"X-Api-Key": READARR_KEY, "Content-Type": "application/json"},
                   data=json.dumps({"path": "/data/books", "name": "Books"}), timeout=10)
print(f"POST: {r2.status_code}")
if r2.status_code in (200, 201):
    print(f"✅ Readarr root folder set: {r2.json().get('path')}")
else:
    # Try without name — check exact schema from a GET on a working app
    print(r2.text[:300])
    # Try just path, no name
    r3 = requests.post(f"http://{READARR_IP}:8787/api/v1/rootfolder",
                       headers={"X-Api-Key": READARR_KEY, "Content-Type": "application/json"},
                       data=json.dumps({"path": "/data/books",
                                        "name": "Books",
                                        "defaultMetadataProfileId": 1,
                                        "defaultQualityProfileId": 1,
                                        "defaultMonitorOption": "all",
                                        "isCalibreLibrary": False}), timeout=10)
    print(f"POST v2: {r3.status_code}")
    if r3.status_code in (200, 201):
        print(f"✅ {r3.json().get('path')}")
    else:
        print(r3.text[:300])
