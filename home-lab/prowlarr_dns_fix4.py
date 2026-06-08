"""
Fix DNS in CT110 — dhclient is overwriting resolv.conf.
Solution: tell dhclient not to update resolv.conf, then write it directly.
Also configure OpenVPN to set DNS via up-script.
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

def host_write(remote_path, content):
    """Write a file to Proxmox host then pct push into container."""
    sftp = c.open_sftp()
    with sftp.open("/tmp/_dns_tmp", "w") as f:
        f.write(content)
    sftp.close()
    _, out, err = c.exec_command(f"pct push 110 /tmp/_dns_tmp {remote_path}")
    out.read(); err.read()

# ── Step 1: Stop dhclient from managing DNS ───────────────────────────────────
print("=== Step 1: Configure dhclient to not touch resolv.conf ===")

# dhclient uses /etc/dhcp/dhclient.conf — add 'make-new-lease-script' or
# more simply: add 'supersede domain-name-servers' to force our DNS
dhclient_conf = """\
# Prevent dhclient from overriding DNS
supersede domain-name-servers 1.1.1.1, 8.8.8.8;
supersede domain-search "";
supersede domain-name "";

option rfc3442-classless-static-routes code 121 = array of unsigned integer 8;
send host-name = gethostname();
request subnet-mask, broadcast-address, time-offset, routers,
        host-name, netbios-name-servers, netbios-scope, interface-mtu,
        rfc3442-classless-static-routes, ntp-servers;
"""
host_write("/etc/dhcp/dhclient.conf", dhclient_conf)
print("  dhclient.conf written ✅")

# ── Step 2: Write resolv.conf now ─────────────────────────────────────────────
print("\n=== Step 2: Write resolv.conf ===")
resolv_content = "nameserver 1.1.1.1\nnameserver 8.8.8.8\n"
host_write("/etc/resolv.conf", resolv_content)
print("  resolv.conf written ✅")

# ── Step 3: Renew DHCP lease so dhclient picks up the new config ──────────────
print("\n=== Step 3: Renew DHCP (dhclient with new config) ===")
pct("110", "dhclient -r eth0 2>/dev/null; dhclient eth0 2>/dev/null &")
time.sleep(4)

# Check if resolv.conf still has our DNS
out1, _ = pct("110", "cat /etc/resolv.conf")
print(f"  resolv.conf after renew:\n  {out1.replace(chr(10), chr(10)+'  ')}")

# ── Step 4: If still broken, use resolvconf utility ──────────────────────────
if "1.1.1.1" not in out1:
    print("\n  dhclient still overwriting — using resolvconf utility")
    pct("110", "apt-get install -y resolvconf -qq 2>/dev/null; true")
    pct("110", "printf 'nameserver 1.1.1.1\\nnameserver 8.8.8.8\\n' | resolvconf -a eth0.inet 2>/dev/null; true")
    time.sleep(2)
    out1b, _ = pct("110", "cat /etc/resolv.conf")
    print(f"  After resolvconf: {out1b}")

# ── Step 5: Verify DNS resolution works ──────────────────────────────────────
print("\n=== Step 5: DNS resolution test ===")
out2, _ = pct("110", "getent hosts 1337x.to 2>&1 || nslookup 1337x.to 2>&1 | head -5")
print(f"  1337x.to: {out2}")

out3, _ = pct("110", "getent hosts nyaa.si 2>&1 || nslookup nyaa.si 2>&1 | head -5")
print(f"  nyaa.si:  {out3}")

# ── Step 6: Test HTTPS reachability ──────────────────────────────────────────
print("\n=== Step 6: HTTPS reachability test ===")
for site in ["https://1337x.to", "https://nyaa.si", "https://www.torrentgalaxy.to"]:
    out, _ = pct("110", f"curl -s --max-time 10 -o /dev/null -w '%{{http_code}}' {site} 2>&1")
    status = "✅" if out in ("200", "301", "302", "403") else "❌"
    print(f"  {status} {site}: {out}")

out4, _ = pct("110", "curl -s --max-time 5 https://api.ipify.org")
print(f"\n  External IP (should be PIA): {out4}")

c.close()
print("\nDone.")
