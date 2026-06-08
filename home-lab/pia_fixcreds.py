"""
Fix PIA OpenVPN: copy pass.txt to /etc/openvpn/pass.txt,
update client.conf auth-user-pass path, restart service.
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
print(f"=== Fixing PIA credentials path on LXC {LXC_ID} ===\n")

# 1. Copy pass.txt to /etc/openvpn/ and lock down permissions
lxc(client, "cp /root/pass.txt /etc/openvpn/pass.txt && chmod 600 /etc/openvpn/pass.txt")

# 2. Update client.conf: change auth-user-pass /root/pass.txt -> auth-user-pass /etc/openvpn/pass.txt
lxc(client, "sed -i 's|auth-user-pass /root/pass.txt|auth-user-pass /etc/openvpn/pass.txt|' /etc/openvpn/client.conf")

# 3. Verify the change
lxc(client, "grep 'auth-user-pass' /etc/openvpn/client.conf")

# 4. Also update client.conf cipher to avoid deprecation warning (add data-ciphers)
lxc(client, r"grep -q 'data-ciphers' /etc/openvpn/client.conf || sed -i '/^cipher aes-128-cbc/a data-ciphers AES-128-CBC' /etc/openvpn/client.conf")

# 5. Restart the service
lxc(client, "systemctl restart openvpn@client")

print("\n[waiting 10s for tunnel to establish...]")
time.sleep(10)

# 6. Status
lxc(client, "systemctl status openvpn@client --no-pager", label="openvpn@client status")

# 7. Check tun0
lxc(client, "ip addr show tun0 2>/dev/null || echo 'tun0 NOT UP'")

# 8. Journal tail
lxc(client, "journalctl -u openvpn@client --no-pager -n 20", label="journal tail")

# 9. Verify external IP changed from 97.70.60.247
lxc(client, "curl -s --max-time 15 https://ipinfo.io/ip")

client.close()
print("\n=== Done ===")
