"""
Set up PIA OpenVPN on Prowlarr LXC (CT110), mirroring the qBittorrent setup.

Steps:
1. Add /dev/net/tun LXC config entries to CT110
2. Restart CT110
3. Install openvpn inside CT110
4. Copy PIA credentials and client.conf from CT109
5. Enable and start openvpn@client
6. Verify tun0 comes up and external IP is PIA
"""
import paramiko, os, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

LXC_ID = "110"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def host(cmd):
    _, out, err = c.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

def pct(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# ── Step 1: Add TUN device config to CT110 LXC conf ──────────────────────────
print("=== Step 1: Add TUN device to CT110 config ===")
conf_path = f"/etc/pve/lxc/{LXC_ID}.conf"
conf, _ = host(f"cat {conf_path}")

tun_lines = [
    "lxc.cgroup.devices.allow: c 10:200 rwm",
    "lxc.mount.entry: /dev/net dev/net none bind,create=dir",
    "lxc.cgroup2.devices.allow: c 10:200 rwm",
    "lxc.mount.entry: /dev/net/tun dev/net/tun none bind,create=file",
]

new_conf = conf
added = []
for line in tun_lines:
    if line not in conf:
        new_conf = new_conf.rstrip() + "\n" + line
        added.append(line)

if added:
    sftp = c.open_sftp()
    with sftp.open(f"/tmp/lxc_{LXC_ID}_tun.conf", "w") as f:
        f.write(new_conf + "\n")
    sftp.close()
    host(f"cp /tmp/lxc_{LXC_ID}_tun.conf {conf_path}")
    print(f"  Added {len(added)} TUN lines")
    for l in added:
        print(f"    + {l}")
else:
    print("  TUN lines already present")

# ── Step 2: Restart CT110 ─────────────────────────────────────────────────────
print("\n=== Step 2: Restarting CT110 ===")
host(f"pct stop {LXC_ID} 2>/dev/null; sleep 3; pct start {LXC_ID} 2>/dev/null")
time.sleep(8)

out, _ = pct(LXC_ID, "ls -la /dev/net/tun 2>/dev/null || echo MISSING")
print(f"  /dev/net/tun: {out}")

# ── Step 3: Install openvpn ───────────────────────────────────────────────────
print("\n=== Step 3: Installing openvpn ===")
out2, err2 = pct(LXC_ID, "apt-get update -qq && apt-get install -y openvpn 2>&1 | tail -5")
print(out2 or err2)

# ── Step 4: Copy PIA credentials and client.conf from CT109 ──────────────────
print("\n=== Step 4: Copying PIA config from CT109 ===")

# Read pass.txt from CT109
pass_txt, _ = pct("109", "cat /etc/openvpn/pass.txt")
print(f"  PIA username: {pass_txt.splitlines()[0] if pass_txt else '(failed)'}")

# Read client.conf from CT109
client_conf, _ = pct("109", "cat /etc/openvpn/client.conf")
print(f"  client.conf: {len(client_conf)} bytes")

# Write to CT110 via temp files on Proxmox host + pct push
sftp = c.open_sftp()
with sftp.open("/tmp/pia_pass.txt", "w") as f:
    f.write(pass_txt)
with sftp.open("/tmp/pia_client.conf", "w") as f:
    f.write(client_conf)
sftp.close()

# mkdir /etc/openvpn in CT110 if needed
pct(LXC_ID, "mkdir -p /etc/openvpn")

host(f"pct push {LXC_ID} /tmp/pia_pass.txt /etc/openvpn/pass.txt")
host(f"pct push {LXC_ID} /tmp/pia_client.conf /etc/openvpn/client.conf")

# Set permissions
pct(LXC_ID, "chmod 600 /etc/openvpn/pass.txt")
print("  Files pushed to CT110 ✅")

# Also copy ovpn files if needed (client.conf references them via ca block inline, so probably not needed)
# Verify the conf doesn't reference external .ovpn files
if "ca " in client_conf and ".ovpn" not in client_conf:
    print("  client.conf uses inline CA — no external .ovpn files needed ✅")
else:
    # Copy the us-chicago.ovpn just in case
    pct(LXC_ID, "mkdir -p /root/openvpn")
    ovpn, _ = pct("109", "cat /root/openvpn/us-chicago.ovpn 2>/dev/null || echo MISSING")
    if ovpn and ovpn != "MISSING":
        sftp = c.open_sftp()
        with sftp.open("/tmp/us_chicago.ovpn", "w") as f:
            f.write(ovpn)
        sftp.close()
        host(f"pct push {LXC_ID} /tmp/us_chicago.ovpn /root/openvpn/us-chicago.ovpn")
        print("  Copied us-chicago.ovpn ✅")

# ── Step 5: Enable ip_forward + openvpn@client ───────────────────────────────
print("\n=== Step 5: Enabling OpenVPN service ===")
pct(LXC_ID, "echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-vpn.conf && sysctl -p /etc/sysctl.d/99-vpn.conf 2>&1")
pct(LXC_ID, "systemctl enable openvpn@client")
out3, err3 = pct(LXC_ID, "systemctl start openvpn@client 2>&1")
print(f"  start: {err3 or out3 or 'ok'}")

print("\n[waiting 10s for tunnel to come up...]")
time.sleep(10)

# ── Step 6: Verify ───────────────────────────────────────────────────────────
print("\n=== Step 6: Verification ===")
out4, _ = pct(LXC_ID, "systemctl is-active openvpn@client")
print(f"  openvpn@client: {out4}")

out5, _ = pct(LXC_ID, "ip addr show tun0 2>/dev/null || echo 'tun0 NOT UP'")
print(f"  tun0: {out5}")

out6, _ = pct(LXC_ID, "curl -s --max-time 10 https://api.ipify.org 2>/dev/null || echo timeout")
print(f"  External IP: {out6}")

# Check journal for errors if not up
if "NOT UP" in out5 or "inactive" in out4:
    print("\n=== Journal (last 20 lines) ===")
    out7, _ = pct(LXC_ID, "journalctl -u openvpn@client --no-pager -n 20")
    print(out7)

c.close()
print("\nDone.")
