"""Test RuTracker reachability and find a working approach."""
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def lxc(vmid, cmd, timeout=25):
    _, out, err = ssh.exec_command(f"pct exec {vmid} -- {cmd}", timeout=timeout)
    stdout = out.read().decode(errors="replace").strip()
    stderr = "\n".join(l for l in err.read().decode(errors="replace").splitlines()
                       if "deprecated" not in l.lower()).strip()
    return stdout or stderr

def host_cmd(cmd, timeout=25):
    _, out, err = ssh.exec_command(cmd, timeout=timeout)
    stdout = out.read().decode(errors="replace").strip()
    stderr = err.read().decode(errors="replace").strip()
    return stdout or stderr

# 1. Simple TCP connect test - no complex bash
print("=== CT110: curl rutracker.org (simple) ===")
result = lxc("110", "curl -s --max-time 10 -o /dev/null -w %{http_code} https://rutracker.org/", timeout=20)
print(f"  rutracker.org: HTTP {result or '(no response / connection refused)'}")

result = lxc("110", "curl -s --max-time 10 -o /dev/null -w %{http_code} https://rutracker.net/", timeout=20)
print(f"  rutracker.net: HTTP {result or '(no response / connection refused)'}")

# 2. Same test from CT107 (no VPN)
print()
print("=== CT107 (no VPN): curl rutracker.org ===")
result = lxc("107", "curl -s --max-time 10 -o /dev/null -w %{http_code} https://rutracker.org/", timeout=20)
print(f"  rutracker.org: HTTP {result or '(no response / connection refused)'}")

# 3. Current PIA region
print()
print("=== CT110: current VPN config ===")
print(lxc("110", "grep remote /etc/openvpn/client.conf"))
print("Public IP:", lxc("110", "curl -s --max-time 5 https://api.ipify.org"))

# 4. Available PIA ovpn files
print()
print("=== CT110: PIA ovpn files ===")
ovpn_list = lxc("110", "ls /root/openvpn/")
print(ovpn_list[:500] if ovpn_list else "  /root/openvpn/ not found")

# 5. Check if rutracker needs a specific region or workaround
# RuTracker is a Russian tracker - it may block non-Russian IPs or VPN IPs
# Try Netherlands / Sweden (sometimes less blocked)
print()
print("=== Checking if rutracker.org is blocked by PIA IP ===")
# Get the PIA IP we're using
pia_ip = lxc("110", "curl -s --max-time 5 https://api.ipify.org")
print(f"  Current PIA exit IP: {pia_ip}")
# Check from Proxmox host (no VPN) - our real IP
host_ip = host_cmd("curl -s --max-time 5 https://api.ipify.org")
print(f"  Home IP (no VPN): {host_ip}")
# Try rutracker from Proxmox host directly
result = host_cmd("curl -s --max-time 10 -o /dev/null -w %{http_code} https://rutracker.org/")
print(f"  rutracker.org from home IP: HTTP {result or '(failed)'}")

ssh.close()
