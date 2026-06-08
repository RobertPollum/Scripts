"""
Finish configuration: Readarr qBT + Bazarr connections.
Uses known-good values discovered from probe scripts.
"""
import requests, json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Known API keys
READARR_IP  = os.environ["READARR_IP"]
READARR_KEY = os.environ["READARR_API_KEY"]
SONARR_IP   = os.environ["SONARR_IP"]
SONARR_KEY  = os.environ["SONARR_API_KEY"]
RADARR_IP   = os.environ["RADARR_IP"]
RADARR_KEY  = os.environ["RADARR_API_KEY"]
BAZARR_IP   = os.environ["BAZARR_IP"]
BAZARR_KEY  = os.environ["BAZARR_API_KEY"]
QBT_HOST    = os.environ["QBITTORRENT_IP"]
QBT_PORT    = 8090
QBT_USER    = "admin"
QBT_PASS    = os.environ["QBITTORRENT_PASSWORD"]


# ── Readarr → qBittorrent ─────────────────────────────────────────────────────
print("=== Readarr → qBittorrent ===")
existing = requests.get(f"http://{READARR_IP}:8787/api/v1/downloadclient",
                        headers={"X-Api-Key": READARR_KEY}).json()
if any(c.get("implementation") == "QBittorrent" for c in existing):
    print("  Already configured")
else:
    schema = requests.get(f"http://{READARR_IP}:8787/api/v1/downloadclient/schema",
                          headers={"X-Api-Key": READARR_KEY}).json()
    tmpl = next(s for s in schema if s.get("implementation") == "QBittorrent")
    # Patch fields
    for f in tmpl["fields"]:
        if f["name"] == "host":           f["value"] = QBT_HOST
        elif f["name"] == "port":         f["value"] = QBT_PORT
        elif f["name"] == "username":     f["value"] = QBT_USER
        elif f["name"] == "password":     f["value"] = QBT_PASS
        elif f["name"] == "musicCategory": f["value"] = "readarr"
    tmpl.update({"name": "qBittorrent", "enable": True, "priority": 1,
                 "removeCompletedDownloads": True, "removeFailedDownloads": True})
    tmpl.pop("id", None)
    r = requests.post(f"http://{READARR_IP}:8787/api/v1/downloadclient",
                      headers={"X-Api-Key": READARR_KEY, "Content-Type": "application/json"},
                      data=json.dumps(tmpl))
    print(f"  Status: {r.status_code}")
    if r.status_code in (200, 201):
        print("  ✅ qBittorrent added to Readarr")
    else:
        print(f"  ❌ {r.text[:300]}")


# ── Bazarr → Sonarr + Radarr ─────────────────────────────────────────────────
print("\n=== Bazarr → Sonarr + Radarr ===")

# Check current Bazarr settings to understand the expected payload shape
current = requests.get(f"http://{BAZARR_IP}:6767/api/system/settings",
                       headers={"X-Api-Key": BAZARR_KEY}).json()
sonarr_current = current.get("sonarr", {})
radarr_current = current.get("radarr", {})
print(f"  Current sonarr.ip: {sonarr_current.get('ip')}")
print(f"  Current radarr.ip: {radarr_current.get('ip')}")

# Build payload by merging our values into the existing structure
payload = {
    "sonarr": {**sonarr_current, "ip": SONARR_IP, "port": 8989,
               "apikey": SONARR_KEY, "ssl": False, "base_url": "/"},
    "radarr": {**radarr_current, "ip": RADARR_IP, "port": 7878,
               "apikey": RADARR_KEY, "ssl": False, "base_url": "/"},
    "general": {**current.get("general", {}), "use_sonarr": True, "use_radarr": True},
}

r = requests.post(f"http://{BAZARR_IP}:6767/api/system/settings",
                  headers={"X-Api-Key": BAZARR_KEY, "Content-Type": "application/json"},
                  data=json.dumps(payload))
print(f"  POST status: {r.status_code}")
if r.status_code in (200, 204):
    print("  ✅ Bazarr connected to Sonarr + Radarr")
else:
    print(f"  ❌ {r.text[:300]}")
    # Try alternate approach: PATCH or PUT
    print("  Trying PUT...")
    r2 = requests.put(f"http://{BAZARR_IP}:6767/api/system/settings",
                      headers={"X-Api-Key": BAZARR_KEY, "Content-Type": "application/json"},
                      data=json.dumps(payload))
    print(f"  PUT status: {r2.status_code} {r2.text[:200]}")
