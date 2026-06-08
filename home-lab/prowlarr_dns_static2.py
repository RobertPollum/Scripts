"""
Permanent DNS fix for CT110 (Prowlarr).
Root cause: eth0 is set to 'dhcp' in /etc/network/interfaces, so dhclient
runs on every boot and overwrites /etc/resolv.conf with the router's DNS.
Fix: Convert eth0 to a static config with hardcoded DNS.
IP is confirmed as PROWLARR_IP (router DHCP reservation).
"""
import paramiko
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_USER = 'root'
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]
CT_ID = 110

STATIC_IP = os.environ["PROWLARR_IP"]
GATEWAY = os.environ["GATEWAY_IP"]
NETMASK = '255.255.255.0'
DNS1 = '1.1.1.1'
DNS2 = '8.8.8.8'


def pct_exec(ssh, cmd):
    full = f"pct exec {CT_ID} -- bash -c \"{cmd}\""
    _, stdout, stderr = ssh.exec_command(full)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out, err


ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(PROXMOX_HOST, username=PROXMOX_USER, password=PROXMOX_PASS, timeout=10)

print("=== CT110 current network state ===")
out, _ = pct_exec(ssh, "ip addr show eth0 && ip route")
print(out)

print("\n=== Backing up /etc/network/interfaces ===")
out2, err2 = pct_exec(ssh, "cp /etc/network/interfaces /etc/network/interfaces.bak")
print(f"  Backup: err={err2 or 'none'}")

print("\n=== Writing static /etc/network/interfaces ===")
new_interfaces = (
    "auto lo\\n"
    "iface lo inet loopback\\n"
    "\\n"
    f"auto eth0\\n"
    f"iface eth0 inet static\\n"
    f"    address {STATIC_IP}\\n"
    f"    netmask {NETMASK}\\n"
    f"    gateway {GATEWAY}\\n"
    f"    dns-nameservers {DNS1} {DNS2}\\n"
)
write_cmd = f"printf '{new_interfaces}' > /etc/network/interfaces"
out3, err3 = pct_exec(ssh, write_cmd)
print(f"  Write: err={err3 or 'none'}")

out4, _ = pct_exec(ssh, "cat /etc/network/interfaces")
print(f"  New interfaces:\n{out4}")

print("\n=== Killing dhclient so it stops managing resolv.conf ===")
out5, err5 = pct_exec(ssh, "pkill dhclient 2>/dev/null; echo killed")
print(f"  {out5}")

print("\n=== Restoring resolv.conf to 1.1.1.1/8.8.8.8 ===")
out6, err6 = pct_exec(ssh, f"printf 'nameserver {DNS1}\\nnameserver {DNS2}\\n' > /etc/resolv.conf")
print(f"  Write: err={err6 or 'none'}")

# Also disable/mask resolvconf if installed, as it can overwrite resolv.conf
out7, _ = pct_exec(ssh, "which resolvconf 2>/dev/null")
if out7:
    out8, err8 = pct_exec(ssh, "systemctl stop resolvconf 2>/dev/null; systemctl disable resolvconf 2>/dev/null")
    print(f"  Disabled resolvconf: err={err8 or 'none'}")

print("\n=== Verifying ===")
out9, _ = pct_exec(ssh, "cat /etc/resolv.conf")
print(f"  resolv.conf: {out9}")

out10, _ = pct_exec(ssh, "nslookup 1337x.to 2>&1 | head -5")
print(f"  DNS test (1337x.to):\n{out10}")

out11, _ = pct_exec(ssh, "ps aux | grep dhclient | grep -v grep")
print(f"  dhclient processes: {out11 or '(none - good)'}")

ssh.close()

print("\n=== DONE ===")
print("eth0 is now static. dhclient will NOT run on next reboot.")
print("DNS is permanently set to 1.1.1.1 / 8.8.8.8.")
print("NOTE: Prowlarr restart not required - DNS is resolved at query time.")
