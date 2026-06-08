"""Find Jellyseerr API key from its config files on CT106."""
import paramiko
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_USER = 'root'
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]
CT_ID = 106


def pct_exec(ssh, cmd):
    full = f"pct exec {CT_ID} -- bash -c \"{cmd}\""
    _, stdout, stderr = ssh.exec_command(full)
    return stdout.read().decode().strip(), stderr.read().decode().strip()


ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(PROXMOX_HOST, username=PROXMOX_USER, password=PROXMOX_PASS, timeout=10)

# Find the Jellyseerr config/db
out, _ = pct_exec(ssh, "find /opt /var /config /root -name 'settings.json' 2>/dev/null | head -5")
print("settings.json locations:", out)

out2, _ = pct_exec(ssh, "find /opt /var /config /root -name '*.db' 2>/dev/null | head -5")
print("DB files:", out2)

# Check common Jellyseerr config paths
out3, _ = pct_exec(ssh, "ls /opt/overseerr/ 2>/dev/null; ls /opt/jellyseerr/ 2>/dev/null; ls /var/lib/jellyseerr/ 2>/dev/null")
print("App dirs:", out3)

# Check process to find data path
out4, _ = pct_exec(ssh, "ps aux | grep -i seerr | grep -v grep")
print("Process:", out4)

# Check systemd service
out5, _ = pct_exec(ssh, "systemctl show jellyseerr --property=ExecStart 2>/dev/null")
print("Service:", out5[:300])

ssh.close()
