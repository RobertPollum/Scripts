"""
Read client.conf and pass.txt contents from qbittorrent LXC,
then show what's needed to fix the PIA OpenVPN setup.
"""
import paramiko
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(Path(__file__).parent / ".env")

HOST = os.environ["PROXMOX_HOST"]
USER = os.environ["PROXMOX_USER"].split("@")[0]
PASS = os.environ["PROXMOX_PASSWORD"]
LXC_ID = "109"


def get_client():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=10)
    return c


def run(client, cmd, label=None):
    _, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    print(f"\n$ {label or cmd}")
    if out:
        print(out, end="")
    if err:
        print("[err]", err, end="")
    return out, err


def lxc(client, inner_cmd, label=None):
    return run(client, f"pct exec {LXC_ID} -- bash -c '{inner_cmd}'", label=label or inner_cmd)


client = get_client()

# Read the full client.conf
lxc(client, "cat /etc/openvpn/client.conf")

# Read pass.txt (just show line count and first line redacted so we confirm format)
lxc(client, "wc -l /root/pass.txt && echo '[line 1 username]:' && head -1 /root/pass.txt | cut -c1-6")

# Check if any PIA ovpn files exist anywhere on the system
lxc(client, "find / -name '*.ovpn' 2>/dev/null | grep -v proc")

# Check what's in /root/
lxc(client, "ls -lah /root/")

client.close()
