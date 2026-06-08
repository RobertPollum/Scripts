"""
Fix NFS root_squash issue.

The QNAP NFS export squashes root → nobody (no write access).
NAS dirs are owned by UID 1000 with 777 perms.

Fix: create 'media' user with UID 1000 in each *arr container,
then run each service as that user (or just chown/chmod the mount point).

Better fix: use the QNAP SSH to set no_root_squash on the export,
OR just verify if the dirs are 777 and any UID can write.
"""
import paramiko, os, requests, json, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

RADARR_IP  = os.environ["RADARR_IP"];   RADARR_KEY  = os.environ["RADARR_API_KEY"]
SONARR_IP  = os.environ["SONARR_IP"];  SONARR_KEY  = os.environ["SONARR_API_KEY"]
READARR_IP = os.environ["READARR_IP"];  READARR_KEY = os.environ["READARR_API_KEY"]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def host(cmd):
    _, out, err = c.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

def pct(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# ── Diagnose: what UID does the write fail as? ───────────────────────────────
print("=== Write test with UID 1000 (NAS owner) ===")
# Create user with uid 1000 in Radarr container and test
out, err = pct("107", "id 1000 2>/dev/null || useradd -u 1000 -M -s /usr/sbin/nologin media 2>/dev/null; su -s /bin/sh media -c 'touch /data/movies/.write_test && rm -f /data/movies/.write_test && echo WRITABLE' 2>&1")
print(f"  Radarr as UID 1000: {out}")

# ── Option A: SSH into QNAP and check/fix NFS export ─────────────────────────
# Try to connect to QNAP NAS
print("\n=== Testing QNAP SSH access ===")
nas = paramiko.SSHClient()
nas.set_missing_host_key_policy(paramiko.AutoAddPolicy())

# Try loading NAS creds from .env
nas_env = {}
env_path = Path(__file__).parent / ".env"
for line in env_path.read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        nas_env[k.strip()] = v.strip()

nas_user = nas_env.get("NAS_USER", "admin")
nas_pass = nas_env.get("NAS_PASSWORD", nas_env.get("NAS_PASS", ""))

try:
    nas.connect(os.environ["NAS_HOST"], username=nas_user, password=nas_pass, timeout=10)
    _, nout, _ = nas.exec_command("cat /etc/exports 2>/dev/null || exportfs -v 2>/dev/null | head -20")
    print(f"NFS exports:\n{nout.read().decode()[:500]}")

    # Check if root_squash is set
    _, nout2, _ = nas.exec_command("cat /etc/exports 2>/dev/null")
    exports = nout2.read().decode()
    print(f"Exports file:\n{exports[:300]}")

    if "no_root_squash" not in exports and "root_squash" in exports:
        print("⚠️  root_squash active — need to change to no_root_squash")
    elif "no_root_squash" in exports:
        print("✅ no_root_squash already set")
    nas.close()
except Exception as e:
    print(f"QNAP SSH failed: {e}")
    print("Will use UID mapping approach instead")

# ── Option B: Use LXC UID mapping to map container root → NAS UID 1000 ────────
# Actually the simpler fix: the dirs are 777, so even nobody can write IF
# the NFS server allows it. Let's check what UID the failed write was as:
print("\n=== Checking effective UID when writing from container ===")
out2, _ = pct("107", "stat -c '%u' /data/movies")
print(f"  /data/movies owner UID seen from container: {out2}")

out3, _ = pct("107", "touch /data/movies/.uid_test 2>&1; ls -la /data/movies/.uid_test 2>/dev/null; rm -f /data/movies/.uid_test 2>/dev/null; echo done")
print(f"  Touch attempt: {out3}")

# The issue is NFS squashes root→nobody (65534) and nobody can't write
# even with 777 IF the NFS server is configured strictly.
# Let's check with id nobody in the container:
out4, _ = pct("107", "id nobody")
print(f"  nobody id: {out4}")

# ── Option C: Add no_root_squash via Proxmox re-mount ────────────────────────
# Can't change server config, but can try anonuid/anongid if server supports it
# Actually, the cleanest LXC solution: use lxc.idmap to remap UIDs

# ── Option D: Override with Proxmox host mount using no_root_squash ──────────
# Try remounting with explicit options including allow writes
print("\n=== Current host mount details ===")
out5, _ = host("nfsstat -m 2>/dev/null | grep -A5 qnap-nfs-Multimedia | head -10")
print(out5)

# Check if we can write as root from Proxmox host to the NAS
out6, err6 = host(f"touch /mnt/pve/qnap-nfs-Multimedia/Videos/movies/.pve_test 2>&1 && rm -f /mnt/pve/qnap-nfs-Multimedia/Videos/movies/.pve_test && echo HOST_WRITABLE || echo 'HOST_READONLY: {err6}'")
print(f"Host write test: {out6}")

c.close()
