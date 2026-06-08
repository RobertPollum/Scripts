"""
Enable and start openvpn@client service inside the qbittorrent LXC,
enable ip_forward, and verify the tun0 interface comes up.
"""
import paramiko
import time
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
    return run(client, f"pct exec {LXC_ID} -- bash -c {repr(inner_cmd)}", label=label or inner_cmd)


client = get_client()
print(f"=== Enabling OpenVPN PIA on LXC {LXC_ID} ===\n")

# 1. Enable ip_forward persistently
lxc(client, "echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-vpn.conf && sysctl -p /etc/sysctl.d/99-vpn.conf")

# 2. Enable and start openvpn@client (uses /etc/openvpn/client.conf)
lxc(client, "systemctl enable openvpn@client")
lxc(client, "systemctl start openvpn@client")

# 3. Wait a few seconds for tunnel to establish
print("\n[waiting 8s for tunnel to come up...]")
time.sleep(8)

# 4. Check service status
lxc(client, "systemctl status openvpn@client --no-pager", label="openvpn@client status")

# 5. Check for tun0 interface
lxc(client, "ip addr show tun0 2>/dev/null || echo 'tun0 NOT UP'")

# 6. Check routing table
lxc(client, "ip route show")

# 7. Verify external IP has changed (uses curl if available)
lxc(client, "curl -s --max-time 10 https://ipinfo.io/ip 2>/dev/null || echo 'curl not available or no internet'")

# 8. Check journal for any errors
lxc(client, "journalctl -u openvpn@client --no-pager -n 30", label="openvpn@client journal (last 30 lines)")

client.close()
print("\n=== Done ===")
