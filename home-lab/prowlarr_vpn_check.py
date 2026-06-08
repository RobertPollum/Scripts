"""Verify Prowlarr CT110 is correctly routing through OpenVPN."""
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def run(vmid, cmd, timeout=20):
    chan = ssh.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(f"pct exec {vmid} -- bash -c \"{cmd}\"")
    stdout = chan.makefile("rb").read().decode(errors="replace").strip()
    stderr = chan.makefile_stderr("rb").read().decode(errors="replace").strip()
    chan.close()
    return stdout or stderr

def run_host(cmd, timeout=20):
    chan = ssh.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)
    stdout = chan.makefile("rb").read().decode(errors="replace").strip()
    stderr = chan.makefile_stderr("rb").read().decode(errors="replace").strip()
    chan.close()
    return stdout or stderr

print("=== 1. OpenVPN service status ===")
print(run("110", "systemctl status openvpn@client --no-pager | head -12"))

print()
print("=== 2. Network interfaces ===")
print(run("110", "ip addr show | grep -E 'inet |^[0-9]+:'"))

print()
print("=== 3. Routing table ===")
print(run("110", "ip route show"))

print()
print("=== 4. Public IP (what the outside world sees) ===")
# Should show a PIA IP, not your home IP
vpn_ip = run("110", "curl -s --max-time 8 https://api.ipify.org 2>/dev/null || curl -s --max-time 8 https://ifconfig.me 2>/dev/null")
print(f"  CT110 public IP: {vpn_ip}")

# Compare with Proxmox host (no VPN)
host_ip = run_host("curl -s --max-time 8 https://api.ipify.org 2>/dev/null")
print(f"  Proxmox host public IP: {host_ip}")

if vpn_ip and host_ip and vpn_ip == host_ip:
    print("  WARNING: Same IP — traffic is NOT going through VPN!")
elif vpn_ip and host_ip:
    print("  GOOD: Different IPs — VPN is routing traffic correctly")

print()
print("=== 5. VPN IP geolocation ===")
geo = run("110", f"curl -s --max-time 8 'https://ipapi.co/{vpn_ip}/json/' 2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin); print(f\\\"  org: {{d.get('org','?')}}  city: {{d.get('city','?')}}  country: {{d.get('country_name','?')}}  ip: {{d.get('ip','?')}}\\\")\" 2>/dev/null")
print(geo or f"  (lookup failed for {vpn_ip})")

print()
print("=== 6. OpenVPN config key settings ===")
print(run("110", "grep -E 'remote|auth-user-pass|dev|route-nopull|pull' /etc/openvpn/client.conf 2>/dev/null"))

print()
print("=== 7. OpenVPN log (last 10 lines) ===")
print(run("110", "journalctl -u openvpn@client --no-pager -n 10 2>/dev/null"))

print()
print("=== 8. DNS config ===")
print(run("110", "cat /etc/resolv.conf"))

ssh.close()
