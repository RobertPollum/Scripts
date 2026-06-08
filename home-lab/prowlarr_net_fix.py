"""Fix CT110 (Prowlarr) network connectivity - restore internet access."""
import paramiko, os, time
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

def run_host(cmd):
    _, out, err = c.exec_command(cmd)
    stdout = out.read().decode().strip()
    stderr = err.read().decode().strip()
    return stdout or stderr

print("=== Step 1: Check current routing table ===")
print(run("110", "ip route show"))

print()
print("=== Step 2: Check all interfaces ===")
print(run("110", "ip addr show"))

print()
print("=== Step 3: Stop OpenVPN to isolate base connectivity ===")
print(run("110", "systemctl stop openvpn@client && echo stopped"))
time.sleep(3)

print()
print("=== Step 4: Test basic connectivity without VPN ===")
print("Routing table:", run("110", "ip route show"))
print("Ping 8.8.8.8:", run("110", "ping -c 2 -W 3 8.8.8.8 2>&1"))
print("DNS test:", run("110", "nslookup google.com 8.8.8.8 2>&1 | head -5"))

print()
print("=== Step 5: Renew DHCP if ping fails ===")
ping_result = run("110", "ping -c 1 -W 3 8.8.8.8 2>&1")
if "1 received" not in ping_result:
    print("No connectivity - trying DHCP renewal...")
    print(run("110", "dhclient -v eth0 2>&1 | tail -5"))
    time.sleep(3)
    print("After DHCP:", run("110", "ping -c 2 -W 3 8.8.8.8 2>&1"))
    print("Route after DHCP:", run("110", "ip route show"))
else:
    print("Base connectivity OK without VPN")

print()
print("=== Step 6: Test DNS ===")
print(run("110", "ping -c 2 -W 3 1.1.1.1 2>&1"))
print(run("110", "nslookup us-chicago.privacy.network 2>&1 | head -8"))

print()
print("=== Step 7: Restart OpenVPN ===")
print(run("110", "systemctl start openvpn@client && echo started"))
time.sleep(10)

print()
print("=== Step 8: Check VPN status after restart ===")
print(run("110", "systemctl status openvpn@client --no-pager | head -15"))
print()
print("tun0:", run("110", "ip addr show tun0 2>/dev/null || echo 'tun0 not up'"))
print("Routes:", run("110", "ip route show"))

print()
print("=== Step 9: Test connectivity through VPN ===")
print("Ping 8.8.8.8:", run("110", "ping -c 2 -W 5 8.8.8.8 2>&1"))
print("DNS:", run("110", "nslookup prowlarr.servarr.com 2>&1 | head -5"))

c.close()
print()
print("Done.")
