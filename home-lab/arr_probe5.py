"""Probe: get Bazarr API key and qBT default password."""
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def run(vmid, cmd):
    _, out, _ = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip()

print("=== Bazarr config.ini ===")
print(run("112", "cat /opt/bazarr/data/config/config.ini 2>/dev/null | head -60"))

print("\n=== qBT: test default password ===")
import requests, json
# qBT web UI is on 8090; test login with admin/adminadmin
_env_qbittorrent_ip = os.environ["QBITTORRENT_IP"]
r = requests.post(f"http://{_env_qbittorrent_ip}:8090/api/v2/auth/login",
                  data={"username": "admin", "password": "adminadmin"})
print("login status:", r.status_code, r.text)

c.close()
