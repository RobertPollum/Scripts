"""Test if Bazarr can reach Sonarr/Radarr, and use Bazarr test endpoint."""
import requests, json, paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

BAZARR_IP  = os.environ["BAZARR_IP"]
BAZARR_KEY = os.environ["BAZARR_API_KEY"]
SONARR_IP  = os.environ["SONARR_IP"]
SONARR_KEY = os.environ["SONARR_API_KEY"]
RADARR_IP  = os.environ["RADARR_IP"]
RADARR_KEY = os.environ["RADARR_API_KEY"]
BASE  = f"http://{BAZARR_IP}:6767"
HDRS  = {"X-Api-Key": BAZARR_KEY, "Content-Type": "application/json"}

# 1. Test Bazarr→Sonarr/Radarr network from inside the Bazarr container
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def pct(vmid, cmd):
    _, out, _ = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip()

print("=== Bazarr → Sonarr reachability ===")
print(pct("112", f"curl -s -o /dev/null -w '%{{http_code}}' http://{SONARR_IP}:8989/api/v3/system/status -H 'X-Api-Key: {SONARR_KEY}'"))
print("=== Bazarr → Radarr reachability ===")
print(pct("112", f"curl -s -o /dev/null -w '%{{http_code}}' http://{RADARR_IP}:7878/api/v3/system/status -H 'X-Api-Key: {RADARR_KEY}'"))

c.close()

# 2. Use Bazarr's /api/system/tests to test connection
print("\n=== Bazarr test Sonarr connection ===")
r = requests.get(f"{BASE}/api/system/tests",
                 headers=HDRS,
                 params={"action": "sonarr", "ip": SONARR_IP, "port": 8989,
                         "apikey": SONARR_KEY, "ssl": "false", "base_url": "/"})
print(f"Test result: {r.status_code} {r.text[:300]}")

print("\n=== Bazarr test Radarr connection ===")
r2 = requests.get(f"{BASE}/api/system/tests",
                  headers=HDRS,
                  params={"action": "radarr", "ip": RADARR_IP, "port": 7878,
                          "apikey": RADARR_KEY, "ssl": "false", "base_url": "/"})
print(f"Test result: {r2.status_code} {r2.text[:300]}")
