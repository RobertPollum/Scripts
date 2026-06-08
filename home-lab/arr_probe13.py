"""Verify qBT login works and test from *arr container."""
import requests, paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

# Test qBT login - 204 may be success in newer qBT versions
s = requests.Session()
_env_qbittorrent_ip = os.environ["QBITTORRENT_IP"]
r = s.post(f"http://{_env_qbittorrent_ip}:8090/api/v2/auth/login",
           data={"username": "admin", "password": os.environ["QBITTORRENT_PASSWORD"]})
print(f"Login: {r.status_code} {r.text!r} cookies={dict(s.cookies)}")

# Try getting version with session cookie
r2 = s.get(f"http://{_env_qbittorrent_ip}:8090/api/v2/app/version")
print(f"Version (with session): {r2.status_code} {r2.text!r}")

# Also check if 204 really is success by trying a protected endpoint
r3 = s.get(f"http://{_env_qbittorrent_ip}:8090/api/v2/torrents/info?limit=1")
print(f"Torrents (with session): {r3.status_code} {r3.text[:100]!r}")
