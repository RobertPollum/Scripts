"""Check Prowlarr LXC (CT110) network and VPN status."""
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def run(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c '{cmd}'")
    stdout = out.read().decode().strip()
    stderr = err.read().decode().strip()
    return stdout or stderr

print("=== CT110 Prowlarr - Network interfaces ===")
print(run("110", "ip addr show | grep -E 'inet |^[0-9]'"))

print()
print("=== CT110 - Default route ===")
print(run("110", "ip route show default"))

print()
print("=== CT110 - VPN (tun0) status ===")
print(run("110", "ip addr show tun0 2>/dev/null || echo 'tun0 not found'"))

print()
print("=== CT110 - openvpn service status ===")
print(run("110", "systemctl status openvpn@client --no-pager -l | head -20"))

print()
print("=== CT110 - DNS resolution test ===")
print(run("110", "nslookup prowlarr.servarr.com 2>&1 | head -10"))

print()
print("=== CT110 - External connectivity test ===")
print(run("110", "curl -s --max-time 5 https://prowlarr.servarr.com 2>&1 | head -5 || echo 'CURL FAILED'"))

print()
print("=== CT110 - Ping test ===")
print(run("110", "ping -c 3 -W 3 8.8.8.8 2>&1"))

c.close()
