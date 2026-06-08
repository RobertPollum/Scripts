"""
Diagnose and fix DNS inside Prowlarr CT110 so indexers resolve correctly through VPN.
"""
import paramiko, os, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def host(cmd):
    _, out, err = c.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

def pct(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

print("=== CT110 DNS diagnosis ===")

out1, _ = pct("110", "cat /etc/resolv.conf")
print(f"resolv.conf:\n{out1}\n")

out2, _ = pct("110", "resolvectl status 2>/dev/null | head -20 || echo 'resolvectl not available'")
print(f"resolvectl:\n{out2}\n")

# Check if DNS pushed by OpenVPN is being applied
out3, _ = pct("110", "cat /etc/openvpn/client.conf | grep -i 'script\\|up\\|dns\\|resolv'")
print(f"VPN DNS settings in client.conf:\n{out3 or '(none)'}\n")

# Check if up/down scripts exist
out4, _ = pct("110", "ls /etc/openvpn/*.sh 2>/dev/null || echo none")
print(f"OpenVPN scripts: {out4}")

# Try resolving a common torrent site
out5, _ = pct("110", "nslookup 1337x.to 2>&1 | head -8 || dig 1337x.to 2>&1 | head -8")
print(f"\nDNS test (1337x.to):\n{out5}")

out6, _ = pct("110", "curl -s --max-time 5 https://api.ipify.org")
print(f"\nExternal IP: {out6}")

# Check if tun0 is still up
out7, _ = pct("110", "ip addr show tun0 2>/dev/null | grep inet | head -2")
print(f"tun0: {out7 or 'NOT UP'}")

print("\n=== Fix: set PIA DNS explicitly ===")
# PIA's DNS servers: 10.0.0.1 (through tunnel) or 1.1.1.1/8.8.8.8 as fallback
# Best practice: use update-resolv-conf script with OpenVPN, or just hardcode good DNS

# Check current nameserver
current_ns, _ = pct("110", "grep nameserver /etc/resolv.conf")
print(f"Current nameservers: {current_ns}")

if "192.168.86" in current_ns or not current_ns:
    print("⚠️  Using local/no DNS — will override with Cloudflare + Google")
    # Write new resolv.conf with reliable public DNS
    pct("110", """cat > /etc/resolv.conf << 'EOF'
nameserver 1.1.1.1
nameserver 8.8.8.8
nameserver 9.9.9.9
EOF""")
    # Make it immutable so DHCP doesn't overwrite it
    pct("110", "chattr +i /etc/resolv.conf 2>/dev/null || echo 'chattr not available'")
    print("  Set nameservers: 1.1.1.1, 8.8.8.8, 9.9.9.9")

    # Test again
    time.sleep(1)
    out8, _ = pct("110", "nslookup 1337x.to 2>&1 | head -5 || curl -s --max-time 5 -o /dev/null -w '%{http_code}' https://1337x.to")
    print(f"\nDNS test after fix:\n{out8}")
else:
    print(f"DNS looks OK: {current_ns}")

    # Just test connectivity
    out9, _ = pct("110", "curl -s --max-time 8 -o /dev/null -w '%{http_code}' https://1337x.to 2>&1")
    print(f"1337x.to HTTP status: {out9}")

    out10, _ = pct("110", "curl -s --max-time 8 -o /dev/null -w '%{http_code}' https://nyaa.si 2>&1")
    print(f"nyaa.si HTTP status: {out10}")

c.close()
print("\nDone.")
