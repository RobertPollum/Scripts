"""
Deep-fix DNS in CT110. resolv.conf keeps getting emptied.
Root cause: chattr fails in unprivileged LXC, and something (networkd/dhcp) 
is overwriting it with empty content.
Fix: disable networkd DNS management, write resolv.conf, keep it writable.
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

def ppct(vmid, cmd):
    o, e = pct(vmid, cmd)
    print(f"  $ {cmd[:60]}")
    if o: print(f"    {o[:200]}")
    if e: print(f"    [err] {e[:100]}")
    return o, e

print("=== Who is managing DNS? ===")
ppct("110", "systemctl is-active systemd-networkd 2>/dev/null")
ppct("110", "systemctl is-active networking 2>/dev/null")
ppct("110", "cat /etc/network/interfaces 2>/dev/null | head -15")
ppct("110", "ls /etc/netplan/ 2>/dev/null")
ppct("110", "cat /run/systemd/network/*.network 2>/dev/null | head -20 || echo none")
ppct("110", "ls -la /etc/resolv.conf")

# The issue: networkd or dhcp client regenerates resolv.conf after we write it
# and chattr +i doesn't work in unprivileged LXC

print("\n=== Fix: configure networkd to not manage DNS ===")
# Option 1: Tell networkd not to set DNS
ppct("110", "mkdir -p /etc/systemd/network")
# Find the .network file for eth0
out_nw, _ = pct("110", "ls /etc/systemd/network/ 2>/dev/null")
print(f"  networkd files: {out_nw or '(none)'}")

out_nw2, _ = pct("110", "ls /lib/systemd/network/ 2>/dev/null | head -5")
print(f"  /lib networkd files: {out_nw2 or '(none)'}")

# Option 2: configure dhclient to not update resolv.conf
ppct("110", "which dhclient 2>/dev/null || echo no-dhclient")
ppct("110", "which udhcpc 2>/dev/null || echo no-udhcpc")

# Option 3: Use /etc/resolvconf/resolv.conf.d/ override
ppct("110", "ls /etc/resolvconf/ 2>/dev/null | head -5 || echo no-resolvconf")

# The cleanest fix for unprivileged LXC: use /etc/dhcp/dhclient.conf to prepend DNS
# or use networkd override

print("\n=== Fix: disable DNS via networkd drop-in ===")
# Create a networkd override that disables DNS assignment
pct("110", "mkdir -p /etc/systemd/network")
pct("110", """cat > /etc/systemd/network/10-eth0-nodns.conf << 'EOF'
[Match]
Name=eth0

[Network]
DHCP=yes
DNS=
UseDNS=no

[DHCP]
UseDNS=no
EOF""")

# Also configure dhclient to not overwrite resolv.conf
ppct("110", "which dhclient 2>/dev/null")
pct("110", "mkdir -p /etc/dhcp")
pct("110", """cat > /etc/dhcp/dhclient.conf << 'EOF'
option rfc3442-classless-static-routes code 121 = array of unsigned integer 8;
send host-name = gethostname();
request subnet-mask, broadcast-address, time-offset, routers,
        domain-name, domain-search,
        host-name, netbios-name-servers, netbios-scope, interface-mtu,
        rfc3442-classless-static-routes, ntp-servers;
EOF""")

# Now write resolv.conf
pct("110", """cat > /etc/resolv.conf << 'EOF'
nameserver 1.1.1.1
nameserver 8.8.8.8
EOF""")

# Restart networking
pct("110", "systemctl restart systemd-networkd 2>/dev/null; true")
time.sleep(3)

# Check if it survived
out_rc, _ = pct("110", "cat /etc/resolv.conf")
print(f"\nresolv.conf after networkd restart: {repr(out_rc)}")

if "1.1.1.1" not in out_rc:
    print("Still getting overwritten — trying bind-mount approach")
    # Write the file on the host and bind-mount it read-only into the container
    # This is the nuclear option but works even in unprivileged LXCs
    host_out, host_err = c.exec_command("cat > /tmp/resolv_110.conf << 'EOF'\nnameserver 1.1.1.1\nnameserver 8.8.8.8\nEOF\necho done")
    _, hout, herr = c.exec_command("cat > /tmp/resolv_110.conf\nnameserver 1.1.1.1\nnameserver 8.8.8.8\n")

    # Use pct push to place the file
    c.exec_command("printf 'nameserver 1.1.1.1\\nnameserver 8.8.8.8\\n' > /tmp/resolv_110.conf")
    time.sleep(1)
    _, hout, herr = c.exec_command("pct push 110 /tmp/resolv_110.conf /etc/resolv.conf")
    time.sleep(2)
    out_rc2, _ = pct("110", "cat /etc/resolv.conf")
    print(f"After pct push: {repr(out_rc2)}")

# ── Final test ────────────────────────────────────────────────────────────────
print("\n=== DNS test ===")
out_t1, _ = pct("110", "nslookup 1337x.to 1.1.1.1 2>&1 | head -5")
print(f"nslookup 1337x.to @1.1.1.1: {out_t1}")

out_t2, _ = pct("110", "curl -4 --dns-servers 1.1.1.1 -s --max-time 8 -o /dev/null -w '%{http_code}' https://1337x.to 2>&1 || curl -s --max-time 8 --resolve 1337x.to:443:$(getent hosts 1337x.to | awk '{print $1}' | head -1) -o /dev/null -w '%{http_code}' https://1337x.to 2>&1")
print(f"1337x.to: {out_t2}")

# Check if curl can reach using explicit DNS
out_t3, _ = pct("110", "curl -s --max-time 8 --connect-to ::1.1.1.1: -o /dev/null -w '%{http_code}' https://1337x.to 2>&1")
print(f"1337x.to via 1.1.1.1: {out_t3}")

# Simplest test: just dig with explicit server
out_t4, _ = pct("110", "dig +short 1337x.to @1.1.1.1 2>/dev/null || host 1337x.to 1.1.1.1 2>/dev/null | head -3")
print(f"dig @1.1.1.1: {out_t4}")

c.close()
