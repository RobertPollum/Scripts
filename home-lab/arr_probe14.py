"""Debug Readarr qBT 400 and Bazarr API endpoint."""
import requests, json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

READARR_KEY = os.environ["READARR_API_KEY"]
BAZARR_KEY = os.environ["BAZARR_API_KEY"]

# 1. Readarr schema POST verbose error
print("=== Readarr qBT schema ===")
_env_readarr_ip = os.environ["READARR_IP"]
r = requests.get(f"http://{_env_readarr_ip}:8787/api/v1/downloadclient/schema",
                 headers={"X-Api-Key": READARR_KEY})
schemas = r.json()
qbt = next((s for s in schemas if s.get("implementation") == "QBittorrent"), None)
print("Fields:", [f["name"] for f in qbt["fields"]])

for f in qbt["fields"]:
    if f["name"] == "host":           f["value"] = os.environ["QBITTORRENT_IP"]
    elif f["name"] == "port":         f["value"] = 8090
    elif f["name"] == "username":     f["value"] = "admin"
    elif f["name"] == "password":     f["value"] = os.environ["QBITTORRENT_PASSWORD"]
    elif f["name"] == "musicCategory": f["value"] = "readarr"

qbt["name"] = "qBittorrent"
qbt["enable"] = True
qbt["priority"] = 1
qbt["removeCompletedDownloads"] = True
qbt["removeFailedDownloads"] = True
qbt.pop("id", None)

r2 = requests.post(f"http://{_env_readarr_ip}:8787/api/v1/downloadclient",
                   headers={"X-Api-Key": READARR_KEY, "Content-Type": "application/json"},
                   data=json.dumps(qbt))
print(f"POST status: {r2.status_code}")
print(f"Response: {r2.text[:600]}")

# 2. Bazarr API - try different endpoints
print("\n=== Bazarr API endpoints ===")
for endpoint in ["/api/system/settings", "/api/system/status", "/api/badges"]:
    r3 = requests.get(f"http://{_env_bazarr_ip}:6767{endpoint}",
                      headers={"X-Api-Key": BAZARR_KEY})
    print(f"{endpoint}: {r3.status_code} {r3.text[:80]}")

# 3. Check if Bazarr uses different auth header name
print("\n=== Bazarr auth header variants ===")
for header in ["X-Api-Key", "apikey", "Authorization"]:
    val = BAZARR_KEY if header != "Authorization" else f"Bearer {BAZARR_KEY}"
    r4 = requests.get(f"http://{_env_bazarr_ip}:6767/api/system/status",
                      headers={header: val})
    print(f"{header}: {r4.status_code}")
