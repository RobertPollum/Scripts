"""
Permanently fix DNS on CT110 (Prowlarr) which has a static IP.
Since DHCP is not used, dhclient.conf is irrelevant.
The correct fix is to either:
  1. Write /etc/resolv.conf and make it immutable (chattr +i)
  2. Or configure static DNS via /etc/network/interfaces (dns-nameservers)
  3. Or via systemd-resolved if active

This script applies both approaches for maximum persistence.
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


def pct_exec(ssh, cmd):
    full = f"pct exec {CT_ID} -- bash -c \"{cmd}\""
    _, stdout, stderr = ssh.exec_command(full)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out, err


ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(PROXMOX_HOST, username=PROXMOX_USER, password=PROXMOX_PASS, timeout=10)

print("=== Diagnosing CT110 network config ===")

# Check current network interfaces config
out, _ = pct_exec(ssh, "cat /etc/network/interfaces")
print(f"  /etc/network/interfaces:\n{out}\n")

# Check if systemd-resolved is active
out2, _ = pct_exec(ssh, "systemctl is-active systemd-resolved 2>/dev/null")
print(f"  systemd-resolved: {out2}")

# Check current resolv.conf (symlink or file?)
out3, _ = pct_exec(ssh, "ls -la /etc/resolv.conf && cat /etc/resolv.conf")
print(f"  resolv.conf:\n{out3}\n")

# Check if immutable
out4, _ = pct_exec(ssh, "lsattr /etc/resolv.conf 2>/dev/null")
print(f"  lsattr: {out4}")

# Check resolvconf
out5, _ = pct_exec(ssh, "which resolvconf 2>/dev/null && resolvconf --version 2>/dev/null")
print(f"  resolvconf: {out5}")

print("\n=== Applying permanent DNS fix ===")

# Step 1: Remove immutable flag if set, then update resolv.conf
pct_exec(ssh, "chattr -i /etc/resolv.conf 2>/dev/null")

# Step 2: Write resolv.conf directly
out6, err6 = pct_exec(ssh, "printf 'nameserver 1.1.1.1\\nnameserver 8.8.8.8\\n' > /etc/resolv.conf")
print(f"  Wrote resolv.conf: err={err6 or 'none'}")

# Step 3: Make it immutable so nothing can overwrite it
out7, err7 = pct_exec(ssh, "chattr +i /etc/resolv.conf")
print(f"  chattr +i result: err={err7 or 'none'}")

# Step 4: Also add dns-nameservers to /etc/network/interfaces if eth0/ens present
out8, _ = pct_exec(ssh, "cat /etc/network/interfaces")
if 'dns-nameservers' not in out8:
    # Append dns-nameservers to the iface block
    # Use sed to add after the last 'address' or 'gateway' line in eth0 block
    sed_cmd = "sed -i '/^iface eth0/,/^$/{ /gateway/a\\\\    dns-nameservers 1.1.1.1 8.8.8.8 }' /etc/network/interfaces 2>/dev/null"
    out9, err9 = pct_exec(ssh, sed_cmd)
    print(f"  Added dns-nameservers to interfaces: err={err9 or 'none'}")
else:
    print("  dns-nameservers already in /etc/network/interfaces")

# Step 5: If systemd-resolved is active, configure it too
if out2 == 'active':
    out10, err10 = pct_exec(ssh, "mkdir -p /etc/systemd/resolved.conf.d && printf '[Resolve]\\nDNS=1.1.1.1 8.8.8.8\\nFallbackDNS=9.9.9.9\\n' > /etc/systemd/resolved.conf.d/dns.conf && systemctl restart systemd-resolved")
    print(f"  Configured systemd-resolved: err={err10 or 'none'}")

# Verify final state
out11, _ = pct_exec(ssh, "lsattr /etc/resolv.conf && cat /etc/resolv.conf")
print(f"\n  Final resolv.conf (with attrs):\n{out11}")

# Test DNS
out12, _ = pct_exec(ssh, "nslookup 1337x.to 2>&1 | head -6")
print(f"\n  DNS test (1337x.to):\n{out12}")

out13, _ = pct_exec(ssh, "nslookup torrentgalaxy.one 2>&1 | head -6")
print(f"\n  DNS test (torrentgalaxy.one):\n{out13}")

ssh.close()
print("\n=== DNS permanently fixed (resolv.conf is now immutable) ===")
