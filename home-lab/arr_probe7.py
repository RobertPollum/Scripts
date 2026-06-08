"""Probe: read Bazarr config.yaml for API key, and qBT password reset approach."""
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

print("=== Bazarr config.yaml ===")
print(run("112", "cat /opt/bazarr/data/config/config.yaml"))

print("\n=== qBT: disable localhost auth + get/reset password ===")
# Option: set WebUI\LocalHostAuth=false so localhost skips auth
# Check if that setting exists already
out = run("109", "grep LocalHostAuth /root/.config/qBittorrent/qBittorrent.conf")
print("LocalHostAuth:", out or "(not set)")

c.close()
