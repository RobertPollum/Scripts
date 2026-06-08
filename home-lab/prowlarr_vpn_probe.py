"""Probe Prowlarr CT110 to check current network state and what's needed for VPN."""
import paramiko, os
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

print("=== CT110 (Prowlarr) LXC config ===")
conf, _ = host("cat /etc/pve/lxc/110.conf")
print(conf)

print("\n=== Current IP / network ===")
out, _ = pct("110", "ip addr show && echo '---' && ip route")
print(out)

print("\n=== OpenVPN installed? ===")
out2, _ = pct("110", "which openvpn 2>/dev/null || echo NOT_INSTALLED")
print(out2)

print("\n=== /dev/net/tun accessible? ===")
out3, _ = pct("110", "ls -la /dev/net/tun 2>/dev/null || echo MISSING")
print(out3)

print("\n=== Check qBT container config for TUN device (reference) ===")
conf109, _ = host("cat /etc/pve/lxc/109.conf")
for l in conf109.splitlines():
    if "tun" in l.lower() or "dev" in l.lower() or "net" in l.lower():
        print(f"  {l}")

print("\n=== PIA ovpn files on qBT container (to copy) ===")
out4, _ = pct("109", "ls /root/openvpn/ 2>/dev/null | head -10")
print(out4)

print("\n=== PIA credentials on qBT container ===")
out5, _ = pct("109", "cat /etc/openvpn/client.conf 2>/dev/null | grep -v '^#' | head -20")
print(out5)
out6, _ = pct("109", "head -1 /etc/openvpn/pass.txt 2>/dev/null && echo '(username found)'")
print(out6)

print("\n=== External IP from qBT (VPN) ===")
out7, _ = pct("109", "curl -s --max-time 5 https://api.ipify.org 2>/dev/null || echo timeout")
print(f"qBT external IP: {out7}")

print("\n=== External IP from Prowlarr (no VPN) ===")
out8, _ = pct("110", "curl -s --max-time 5 https://api.ipify.org 2>/dev/null || echo timeout")
print(f"Prowlarr external IP: {out8}")

c.close()
