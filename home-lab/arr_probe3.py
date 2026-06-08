"""Probe: check qBT web UI accessibility and find Bazarr config."""
import paramiko, os, requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def run(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# Check qBT web UI is reachable from Proxmox host
print("=== qBT reachability from Proxmox host ===")
out, err = run("109", "ss -tlnp | grep 8080")
print("qBT listening:", out)
# Try curl from Proxmox host itself
_, curl_out, curl_err = c.exec_command(f"curl -s -o /dev/null -w '%{{http_code}}' http://{os.environ['QBITTORRENT_IP']}:8080")
print("HTTP from Proxmox host:", curl_out.read().decode().strip())

# Check if qBT requires login (default creds admin/adminadmin)
_, curl_out2, _ = c.exec_command(f"curl -s http://{os.environ['QBITTORRENT_IP']}:8080/api/v2/app/version")
print("qBT version (no auth):", curl_out2.read().decode().strip())

# Check what creds qBT is using
out2, _ = run("109", "grep -i 'WebUI\\|password\\|username' /etc/qbittorrent/qBittorrent.conf 2>/dev/null | head -20")
print("qBT config:", out2)
out3, _ = run("109", "find / -name 'qBittorrent.conf' 2>/dev/null | grep -v proc | grep -v sys")
print("qBT conf path:", out3)

# Bazarr - find where config actually lives
print("\n=== Bazarr config ===")
out4, _ = run("112", "find / -maxdepth 8 -name '*.ini' 2>/dev/null | grep -v proc | grep -v sys | grep -v dpkg")
print("ini files:", out4)
out5, _ = run("112", "ls /opt/bazarr/")
print("opt/bazarr:", out5)
out6, _ = run("112", "cat /opt/bazarr/bazarr/config/config.ini 2>/dev/null | head -30")
print("config.ini content:", out6)

c.close()
