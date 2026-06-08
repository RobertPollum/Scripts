"""
Fix NFS root_squash by SSHing into QNAP and updating the export,
then remount on Proxmox and set root folders in *arr apps.
"""
import paramiko, os, requests, json, time

load_dotenv(Path(__file__).parent / ".env")
from dotenv import load_dotenv
from pathlib import Path

# Load both env files
home_env = {}
for line in (Path(__file__).parent / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        home_env[k.strip()] = v.strip()

nas_env = {}
for line in (Path(__file__).parent.parent / "nas-ssh" / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        nas_env[k.strip()] = v.strip()

RADARR_IP  = os.environ["RADARR_IP"];   RADARR_KEY  = os.environ["RADARR_API_KEY"]
SONARR_IP  = os.environ["SONARR_IP"];  SONARR_KEY  = os.environ["SONARR_API_KEY"]
READARR_IP = os.environ["READARR_IP"];  READARR_KEY = os.environ["READARR_API_KEY"]

# ── Connect to Proxmox ────────────────────────────────────────────────────────
prox = paramiko.SSHClient()
prox.set_missing_host_key_policy(paramiko.AutoAddPolicy())
prox.connect(home_env["PROXMOX_HOST"], username="root", password=home_env["PROXMOX_PASSWORD"])

def host(cmd):
    _, out, err = prox.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

def pct(vmid, cmd):
    _, out, err = prox.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# ── Connect to QNAP ───────────────────────────────────────────────────────────
print("=== Connecting to QNAP ===")
nas = paramiko.SSHClient()
nas.set_missing_host_key_policy(paramiko.AutoAddPolicy())
nas.connect(
    nas_env["QNAP_SSH_HOST"],
    username=nas_env["QNAP_SSH_USERNAME"],
    password=nas_env["QNAP_SSH_PASSWORD"],
    timeout=15,
)
print("Connected ✅")

def qnap(cmd):
    _, out, err = nas.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

# ── Check current NFS exports on QNAP ────────────────────────────────────────
print("\n=== Current NFS exports ===")
out, err = qnap("cat /etc/exports 2>/dev/null || exportfs -v 2>/dev/null")
print(out[:600] or err[:200])

# QNAP stores NFS exports in /etc/exports or managed via its own config
# Check where the Multimedia share export is defined
print("\n=== Finding NFS config files ===")
out2, _ = qnap("find /etc /usr/local/etc -name 'exports' -o -name 'nfs*' 2>/dev/null | head -10")
print(out2)

out3, _ = qnap("cat /etc/exports 2>/dev/null")
print("exports:", out3[:400])

# QNAP typically manages exports via /etc/exports
# Check squash settings
print("\n=== Squash settings for Multimedia ===")
out4, _ = qnap("grep -i 'multimedia\\|squash\\|root' /etc/exports 2>/dev/null")
print(out4 or "(not found in /etc/exports)")

# Check the actual export for our Proxmox IP
out5, _ = qnap("exportfs -v 2>/dev/null | grep -i 'multimedia\\|86.93'")
print("exportfs:", out5 or "(not found)")

nas.close()
prox.close()
