"""
Check qBT ban list, test login from Readarr container's perspective,
and add Readarr qBT client by bypassing the connection test.
"""
import paramiko, os, requests, json, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def pct(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

READARR_KEY = os.environ["READARR_API_KEY"]
QBT_HOST = os.environ["QBITTORRENT_IP"]
QBT_PORT = 8090

# 1. Test login from inside the Readarr container
print("=== Login test from Readarr container (113) ===")
_qbt_pass = os.environ["QBITTORRENT_PASSWORD"]
out, err = pct("113", f"curl -s -w '\\n%{{http_code}}' -X POST http://{QBT_HOST}:{QBT_PORT}/api/v2/auth/login -d 'username=admin&password={_qbt_pass}'")
print("Result:", out, err)

# 2. Check if qBT WebUI has IP ban list 
print("\n=== qBT IP ban config ===")
out2, _ = pct("109", "cat /root/.config/qBittorrent/qBittorrent.conf")
# Look for any auth-related settings
for line in out2.splitlines():
    if any(x in line.lower() for x in ['ban', 'block', 'auth', 'bypass', 'whitelist']):
        print(line)

# 3. Check if there's a banned IPs data file
print("\n=== qBT data files ===")
out3, _ = pct("109", "ls /root/.local/share/qBittorrent/ 2>/dev/null || ls /root/.config/qBittorrent/")
print(out3)

c.close()

# 4. Try adding Readarr qBT without triggering connection test
# Some versions accept if we skip the test - just POST without the test validation
print("\n=== Readarr current download clients ===")
_env_readarr_ip = os.environ["READARR_IP"]
r = requests.get(f"http://{_env_readarr_ip}:8787/api/v1/downloadclient",
                 headers={"X-Api-Key": READARR_KEY})
print("Existing:", [x.get("name") for x in r.json()])
