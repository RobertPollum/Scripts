"""Probe: qBT web UI config + Bazarr data dir config."""
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

# qBT: check config and listening ports
print("=== qBittorrent (109) ===")
print("conf:", run("109", "cat /root/.config/qBittorrent/qBittorrent.conf 2>/dev/null"))
print("listening:", run("109", "ss -tlnp 2>/dev/null"))

# Bazarr: check data dir
print("\n=== Bazarr (112) data dir ===")
print("ls data:", run("112", "ls /opt/bazarr/data/ 2>/dev/null"))
print("config.ini:", run("112", "cat /opt/bazarr/data/config.ini 2>/dev/null | head -40"))

c.close()
