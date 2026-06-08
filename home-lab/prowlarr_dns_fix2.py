"""
Fix DNS in Prowlarr CT110.
The router (GATEWAY_IP) can't resolve torrent sites (NXDOMAIN).
nslookup is trying ::1/localhost — systemd-resolved stub listener is intercepting.
Fix: disable stub listener and point directly at 1.1.1.1.
"""
import paramiko, os, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def pct(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

print("=== Diagnosing resolv.conf state ===")
out1, _ = pct("110", "cat /etc/resolv.conf")
print(f"resolv.conf: {out1}")

out2, _ = pct("110", "ls -la /etc/resolv.conf")
print(f"resolv.conf symlink: {out2}")

out3, _ = pct("110", "systemctl is-active systemd-resolved 2>/dev/null")
print(f"systemd-resolved: {out3}")

# ── Fix: remove symlink, write real resolv.conf, disable resolved stub ────────
print("\n=== Fixing DNS ===")

# 1. Remove immutable flag if set
pct("110", "chattr -i /etc/resolv.conf 2>/dev/null; true")

# 2. If resolv.conf is a symlink to stub-resolv.conf, replace it
pct("110", "[ -L /etc/resolv.conf ] && rm /etc/resolv.conf; true")

# 3. Write real resolv.conf
pct("110", """cat > /etc/resolv.conf << 'EOF'
nameserver 1.1.1.1
nameserver 8.8.8.8
EOF""")

# 4. Make immutable so DHCP/networkd can't overwrite it
pct("110", "chattr +i /etc/resolv.conf 2>/dev/null; true")

# 5. Disable systemd-resolved stub if running (it puts 127.0.0.53 which blocks)
out4, _ = pct("110", "systemctl is-active systemd-resolved 2>/dev/null")
if "active" in out4:
    pct("110", "mkdir -p /etc/systemd/resolved.conf.d")
    pct("110", """cat > /etc/systemd/resolved.conf.d/no-stub.conf << 'EOF'
[Resolve]
DNSStubListener=no
EOF""")
    pct("110", "systemctl restart systemd-resolved 2>/dev/null; true")
    print("  Disabled systemd-resolved stub listener")

# 6. Verify
time.sleep(1)
out5, _ = pct("110", "cat /etc/resolv.conf")
print(f"\nNew resolv.conf:\n{out5}")

out6, _ = pct("110", "nslookup 1337x.to 2>&1 | head -6")
print(f"\nnslookup 1337x.to:\n{out6}")

out7, _ = pct("110", "nslookup nyaa.si 2>&1 | head -6")
print(f"\nnslookup nyaa.si:\n{out7}")

# Test actual HTTPS reachability
out8, _ = pct("110", "curl -s --max-time 8 -o /dev/null -w '%{http_code}' https://1337x.to 2>&1")
print(f"\n1337x.to HTTP: {out8}")

out9, _ = pct("110", "curl -s --max-time 8 -o /dev/null -w '%{http_code}' https://nyaa.si 2>&1")
print(f"nyaa.si HTTP: {out9}")

out10, _ = pct("110", "curl -s --max-time 5 https://api.ipify.org")
print(f"External IP (VPN): {out10}")

c.close()
print("\nDone.")
