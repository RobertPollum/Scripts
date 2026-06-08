"""
Set up Tailscale exit node on Proxmox as a new LXC (VMID 115).
- Creates a Debian 12 unprivileged LXC with nesting enabled
- Installs Tailscale via official install script
- Configures IP forwarding
- Brings up Tailscale and prints the login URL to auth to your account
- Advertises as an exit node so you can route traffic through home when away

After this script completes:
  1. Open the login URL printed below and authenticate with your Tailscale account
  2. In the Tailscale admin console, approve the exit node:
     https://login.tailscale.com/admin/machines
"""
import paramiko, os, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]
VMID         = "115"
HOSTNAME     = "tailscale"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def host(cmd, timeout=60):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    return out.read().decode().strip(), err.read().decode().strip()

def pct(vmid, cmd, timeout=120):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}", timeout=timeout)
    return out.read().decode().strip(), err.read().decode().strip()

# ── Check if VMID already exists ──────────────────────────────────────────────
print("=== Checking existing containers ===")
out_list, _ = host("pct list")
print(out_list)

if VMID in out_list:
    print(f"CT{VMID} already exists — skipping creation")
else:
    # ── Find a Debian 12 template ─────────────────────────────────────────────
    print("\n=== Finding Debian 12 template ===")
    templates, _ = host("pveam list local 2>/dev/null | grep -i debian-12")
    if not templates:
        print("No Debian 12 template found — downloading...")
        host("pveam update 2>&1 | tail -3", timeout=30)
        host("pveam download local debian-12-standard_12.7-1_amd64.tar.zst 2>&1 | tail -5", timeout=120)
        templates, _ = host("pveam list local | grep debian-12")
    template = templates.strip().splitlines()[-1].split()[0]
    print(f"Using template: {template}")

    # ── Create unprivileged LXC ───────────────────────────────────────────────
    print(f"\n=== Creating CT{VMID} ({HOSTNAME}) ===")
    create_cmd = (
        f"pct create {VMID} {template} "
        f"--hostname {HOSTNAME} "
        f"--cores 1 --memory 512 --swap 256 "
        f"--rootfs local-lvm:4 "
        f"--net0 name=eth0,bridge=vmbr0,ip=dhcp,type=veth "
        f"--ostype debian "
        f"--features nesting=1 "
        f"--unprivileged 1 "
        f"--onboot 1 "
        f"--password {PROXMOX_PASS!r} "
        f"--start 1"
    )
    out_create, err_create = host(create_cmd, timeout=60)
    print(out_create or err_create)
    time.sleep(5)

    # ── Add TUN device mount (required for Tailscale / WireGuard) ────────────
    print(f"  Adding /dev/net/tun mount to CT{VMID} config...")
    host(f"pct stop {VMID} 2>/dev/null; true")
    time.sleep(3)
    host(f"echo 'lxc.mount.entry: /dev/net dev/net none bind,create=dir' >> /etc/pve/lxc/{VMID}.conf")
    host(f"pct start {VMID}")
    time.sleep(8)
    print("  TUN device mount added ✅")

# ── Start container if not running ───────────────────────────────────────────
status_out, _ = host(f"pct status {VMID}")
print(f"\nCT{VMID} status: {status_out}")
if "stopped" in status_out:
    host(f"pct start {VMID}")
    time.sleep(8)

# ── Get container IP ──────────────────────────────────────────────────────────
print(f"\n=== Getting CT{VMID} IP ===")
CT_IP = ""
for attempt in range(8):
    ip_out, _ = pct(VMID, "ip -4 addr show eth0 2>/dev/null | grep inet | awk '{print $2}' | cut -d/ -f1")
    if ip_out:
        CT_IP = ip_out.strip()
        break
    print(f"  Waiting for IP... (attempt {attempt+1})")
    time.sleep(5)
print(f"CT{VMID} IP: {CT_IP or 'unknown (DHCP may be slow)'}")

# ── Enable IP forwarding ──────────────────────────────────────────────────────
print(f"\n=== Enabling IP forwarding ===")
pct(VMID,
    "echo 'net.ipv4.ip_forward = 1' > /etc/sysctl.d/99-tailscale.conf && "
    "echo 'net.ipv6.conf.all.forwarding = 1' >> /etc/sysctl.d/99-tailscale.conf && "
    "sysctl -p /etc/sysctl.d/99-tailscale.conf")
print("  IP forwarding enabled ✅")

# ── Install Tailscale ─────────────────────────────────────────────────────────
print(f"\n=== Installing Tailscale ===")
ts_check, _ = pct(VMID, "tailscale --version 2>/dev/null || echo NOT_INSTALLED")
if "NOT_INSTALLED" in ts_check:
    print("  Installing Tailscale via official script...")
    out, err = pct(VMID,
        "apt-get update -qq && "
        "apt-get install -y -qq curl 2>&1 | tail -2 && "
        "curl -fsSL https://tailscale.com/install.sh | sh 2>&1 | tail -10",
        timeout=180)
    print(out[-600:] if out else err[-300:])

    ts_ver, _ = pct(VMID, "tailscale --version 2>/dev/null || echo NOT_INSTALLED")
    print(f"  Tailscale: {ts_ver}")
else:
    print(f"  Tailscale already installed: {ts_check} ✅")

# ── Start tailscaled service ──────────────────────────────────────────────────
print(f"\n=== Starting tailscaled service ===")
pct(VMID, "systemctl enable tailscaled && systemctl start tailscaled")
time.sleep(3)
svc_status, _ = pct(VMID, "systemctl is-active tailscaled")
print(f"  tailscaled: {svc_status}")

# ── Bring up Tailscale (advertise exit node, no auth key — manual login) ──────
print(f"\n=== Bringing up Tailscale ===")
up_out, up_err = pct(VMID,
    f"tailscale up --advertise-exit-node --advertise-routes={os.environ['LOCAL_SUBNET']} --accept-routes 2>&1 || true",
    timeout=30)
output = up_out or up_err

# Extract the login URL from the output
login_url = ""
for line in output.splitlines():
    if "https://login.tailscale.com" in line:
        login_url = line.strip()
        break

print()
print("=" * 60)
print("ACTION REQUIRED: Authenticate Tailscale")
print("=" * 60)
if login_url:
    print(f"\nOpen this URL in your browser to log in:\n\n  {login_url}\n")
else:
    print("\nLogin URL not captured in output. Run this on the container to get it:")
    print(f"\n  pct exec {VMID} -- tailscale up --advertise-exit-node\n")
    print("Raw output:")
    print(output[:500])

print("After logging in:")
print("  1. Go to https://login.tailscale.com/admin/machines")
print("  2. Find this machine and approve it as an exit node (via '...' menu)")
print(f"\nContainer: CT{VMID} / {HOSTNAME} @ {CT_IP or 'check Proxmox DHCP'}")
print("=" * 60)

c.close()
