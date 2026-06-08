"""Test RuTracker reachability and find a working PIA region."""
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def run(cmd, timeout=30):
    _, out, err = ssh.exec_command(cmd, timeout=timeout)
    stdout = out.read().decode(errors="replace").strip()
    stderr = "\n".join(l for l in err.read().decode(errors="replace").splitlines()
                       if "deprecated" not in l.lower()).strip()
    return stdout or stderr

def lxc(vmid, cmd, timeout=30):
    return run(f"pct exec {vmid} -- bash -c '{cmd}' 2>/dev/null", timeout=timeout)

# 1. Confirm the block from CT110 with verbose output
print("=== CT110: rutracker.org TCP connect test ===")
print(lxc("110", "curl -v --max-time 10 https://rutracker.org/ 2>&1 | grep -E 'Trying|Connected|SSL|Failed|refused|reset|timeout|Could not'", timeout=20))

# 2. Test from CT107 (no VPN) to confirm it's the VPN IP being blocked
print()
print("=== CT107 (no VPN): rutracker.org TCP connect test ===")
print(lxc("107", "curl -v --max-time 10 https://rutracker.org/ 2>&1 | grep -E 'Trying|Connected|SSL|Failed|refused|reset|timeout|Could not'", timeout=20))

# 3. Check available PIA .ovpn files on CT110
print()
print("=== PIA .ovpn regions available on CT110 ===")
print(lxc("110", "ls /root/openvpn/*.ovpn 2>/dev/null | xargs -I{} basename {} .ovpn | grep -i 'us\\|uk\\|nether\\|swed\\|swiss\\|german\\|france\\|japan' | head -20"))

# 4. Check current PIA region
print()
print("=== Current PIA connection ===")
print(lxc("110", "grep 'remote ' /etc/openvpn/client.conf 2>/dev/null"))
print(lxc("110", "curl -s --max-time 5 https://api.ipify.org 2>/dev/null"))

ssh.close()
