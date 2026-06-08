"""
Switch Prowlarr (CT110) PIA region to one that can reach RuTracker.
Tests candidate regions and switches to the first working one.
"""
import paramiko, os, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def lxc(vmid, cmd, timeout=25):
    _, out, err = ssh.exec_command(f"pct exec {vmid} -- {cmd}", timeout=timeout)
    return out.read().decode(errors="replace").strip()

def host_cmd(cmd, timeout=25):
    _, out, _ = ssh.exec_command(cmd, timeout=timeout)
    return out.read().decode(errors="replace").strip()

# PIA server hostnames to try (European + other regions less likely to be blocked by RuTracker)
# PIA hostname format: <region>.privacy.network
candidates = [
    "nl.privacy.network",        # Netherlands
    "sweden.privacy.network",    # Sweden
    "swiss.privacy.network",     # Switzerland
    "germany.privacy.network",   # Germany
    "france.privacy.network",    # France
    "uk-london.privacy.network", # UK London
    "us-newyorkcity.privacy.network",  # US NYC (different exit than Chicago)
    "us-texas.privacy.network",  # US Texas
]

print("=== Current PIA config ===")
current = lxc("110", "grep '^remote ' /etc/openvpn/client.conf")
print(f"  {current}")

# Check which PIA config files exist on CT110
print()
print("=== Available PIA .ovpn files on CT110 ===")
ovpn_files = lxc("110", "ls /etc/openvpn/ 2>/dev/null")
print(f"  /etc/openvpn/: {ovpn_files}")
ovpn_root = lxc("110", "ls /root/openvpn/ 2>/dev/null | head -20")
print(f"  /root/openvpn/: {ovpn_root or '(not found)'}")

# Strategy: just change the 'remote' line in client.conf to try different regions
# PIA uses port 1198 UDP for all regions
print()
print("=== Testing PIA regions against rutracker.org ===")
working_region = None

for region in candidates:
    print(f"\n  Testing {region}...")
    
    # Update remote in client.conf
    host_cmd(f"pct exec 110 -- sed -i 's|^remote .*|remote {region} 1198|' /etc/openvpn/client.conf")
    
    # Verify the change
    new_remote = lxc("110", "grep '^remote ' /etc/openvpn/client.conf")
    print(f"    Config: {new_remote}")
    
    # Restart OpenVPN
    lxc("110", "systemctl restart openvpn@client", timeout=10)
    print(f"    Waiting for VPN to connect...")
    time.sleep(12)
    
    # Check VPN connected
    vpn_status = lxc("110", "systemctl is-active openvpn@client")
    tun_ip = lxc("110", "ip addr show tun0 2>/dev/null | grep 'inet ' | awk '{print $2}'")
    pub_ip = lxc("110", "curl -s --max-time 6 https://api.ipify.org 2>/dev/null")
    print(f"    VPN: {vpn_status}, tun0: {tun_ip}, public: {pub_ip}")
    
    if vpn_status != "active" or not tun_ip:
        print(f"    VPN didn't connect, skipping")
        continue
    
    # Test rutracker.org
    rut_code = lxc("110", "curl -s --max-time 10 -o /dev/null -w %{http_code} https://rutracker.org/", timeout=20)
    print(f"    rutracker.org: HTTP {rut_code}")
    
    if rut_code in ("200", "301", "302"):
        print(f"    --> WORKS! Keeping {region}")
        working_region = region
        break
    else:
        print(f"    --> Blocked, trying next region")

print()
if working_region:
    print(f"=== SUCCESS: Switched to {working_region} ===")
    print(f"  rutracker.org is now reachable from CT110")
    print(f"  You can now add RuTracker in Prowlarr UI.")
else:
    print("=== All tested regions blocked by rutracker.org ===")
    print("  Reverting to us-chicago...")
    host_cmd("pct exec 110 -- sed -i 's|^remote .*|remote us-chicago.privacy.network 1198|' /etc/openvpn/client.conf")
    lxc("110", "systemctl restart openvpn@client", timeout=10)
    time.sleep(10)
    print("  Reverted. RuTracker may require a non-VPN approach.")

print()
print("=== Final VPN state ===")
final_remote = lxc("110", "grep '^remote ' /etc/openvpn/client.conf")
final_tun = lxc("110", "ip addr show tun0 2>/dev/null | grep 'inet '")
final_pub = lxc("110", "curl -s --max-time 6 https://api.ipify.org 2>/dev/null")
print(f"  Config: {final_remote}")
print(f"  tun0: {final_tun}")
print(f"  Public IP: {final_pub}")

ssh.close()
