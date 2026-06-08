"""
Diagnose OpenVPN/PIA setup inside the qbittorrent LXC (ID 109)
by running commands via 'pct exec' on the Proxmox host.
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
    """Run a command inside the LXC via pct exec."""
    return run(client, f"pct exec {LXC_ID} -- bash -c {repr(inner_cmd)}", label=label or inner_cmd)


client = get_client()
print(f"=== Diagnosing LXC {LXC_ID} via Proxmox {HOST} ===\n")

# OS
lxc(client, "uname -a")
lxc(client, "cat /etc/os-release | head -4")

# OpenVPN binary
lxc(client, "which openvpn && openvpn --version 2>&1 | head -2")

# TUN device
lxc(client, "ls -la /dev/net/tun")

# All files under /etc/openvpn/
lxc(client, "find /etc/openvpn -type f | sort")

# Show directory listing with sizes
lxc(client, "ls -lah /etc/openvpn/")
lxc(client, "ls -lah /etc/openvpn/client/ 2>/dev/null || echo 'no client/ subdir'")

# Show contents of any .ovpn or .conf files
lxc(client, "find /etc/openvpn -name '*.ovpn' -o -name '*.conf' | sort | head -5 | xargs -I{} sh -c 'echo \"=== {} ===\"; cat {}'")

# Check for credentials/auth file
lxc(client, "find /etc/openvpn /root /home -name '*.txt' -o -name 'auth*' -o -name 'login*' -o -name 'creds*' 2>/dev/null | grep -v proc | sort")
lxc(client, "cat /etc/openvpn/login.txt 2>/dev/null || cat /etc/openvpn/auth.txt 2>/dev/null || cat /etc/openvpn/credentials.txt 2>/dev/null || echo '[no standard creds file found at /etc/openvpn/]'")

# Check auth-user-pass directive in any config
lxc(client, "grep -r 'auth-user-pass' /etc/openvpn/ 2>/dev/null || echo 'auth-user-pass not referenced in any config'")

# systemd service status
lxc(client, "systemctl status openvpn 2>&1 | head -20")
lxc(client, "systemctl status 'openvpn@*' 2>&1 | head -20")
lxc(client, "systemctl list-units --all 'openvpn*' 2>&1")

# ip_forward
lxc(client, "cat /proc/sys/net/ipv4/ip_forward")

# Network interfaces
lxc(client, "ip addr show")

# Try to start openvpn manually with the first .ovpn found and capture error
lxc(client, """
ovpn=$(find /etc/openvpn -name '*.ovpn' | head -1)
if [ -z "$ovpn" ]; then
  echo 'NO .ovpn FILE FOUND'
else
  echo "Testing config: $ovpn"
  openvpn --config "$ovpn" --verb 3 --connect-timeout 10 2>&1 &
  PID=$!
  sleep 5
  kill $PID 2>/dev/null
fi
""", label="openvpn test run (5s)")

client.close()
print("\n=== Diagnostic complete ===")
