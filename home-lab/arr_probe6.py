"""Probe: qBT password hash details + Bazarr API key via HTTP."""
import paramiko, os, requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def run(vmid, cmd):
    _, out, _ = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip()

# qBT: check if bypass auth is possible (localhost requests bypass auth by default)
# qBT has a setting: WebUI\LocalHostAuth=false means localhost skips auth
print("=== qBT WebUI config ===")
conf = run("109", "grep -i 'WebUI' /root/.config/qBittorrent/qBittorrent.conf")
print(conf)

# Test from inside the LXC (localhost) - qBT skips auth for localhost by default
print("\n=== qBT version from localhost (no auth) ===")
ver = run("109", "curl -s http://127.0.0.1:8090/api/v2/app/version")
print("version:", ver)

# Bazarr: check if API auth is disabled or get key via HTTP
print("\n=== Bazarr API key via HTTP ===")
# Try without auth first
_env_bazarr_ip = os.environ["BAZARR_IP"]
r = requests.get(f"http://{_env_bazarr_ip}:6767/api/system/status")
print("Bazarr status (no auth):", r.status_code, r.text[:200])

# Check if Bazarr has auth disabled in its config
print("\n=== Bazarr data/config dir ===")
print(run("112", "ls /opt/bazarr/data/config/"))
print(run("112", "cat /opt/bazarr/data/config/config.ini 2>/dev/null"))

c.close()
