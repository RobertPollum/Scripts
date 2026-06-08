"""Debug: test qBT login + verify Bazarr key works."""
import requests, json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_env_qbittorrent_ip = os.environ["QBITTORRENT_IP"]
QBT = f"http://{_env_qbittorrent_ip}:8090"
_env_bazarr_ip = os.environ["BAZARR_IP"]
BAZARR = f"http://{_env_bazarr_ip}:6767"
BAZARR_KEY = os.environ["BAZARR_API_KEY"]

# 1. qBT login test
print("=== qBT login ===")
s = requests.Session()
r = s.post(f"{QBT}/api/v2/auth/login", data={"username": "admin", "password": os.environ["QBITTORRENT_PASSWORD"]})
print(f"login: {r.status_code} {r.text!r}")
r2 = s.get(f"{QBT}/api/v2/app/version")
print(f"version: {r2.status_code} {r2.text!r}")

# 2. Bazarr API key test
print("\n=== Bazarr API key test ===")
r3 = requests.get(f"{BAZARR}/api/system/status", headers={"X-Api-Key": BAZARR_KEY})
print(f"status: {r3.status_code} {r3.text[:200]}")
