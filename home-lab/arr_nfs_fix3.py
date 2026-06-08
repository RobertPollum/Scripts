"""
Add Proxmox host (PROXMOX_HOST) as rw,no_root_squash to QNAP NFS
Multimedia export, remount on Proxmox, then set root folders.
"""
import paramiko, os, requests, json, time, re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

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
PROXMOX_IP = os.environ["PROXMOX_HOST"]
NFS_OPTS   = f"sec=sys,rw,async,wdelay,insecure,no_subtree_check,no_root_squash"

# ── QNAP: patch /etc/exports ─────────────────────────────────────────────────
print("=== Patching QNAP /etc/exports ===")
nas = paramiko.SSHClient()
nas.set_missing_host_key_policy(paramiko.AutoAddPolicy())
nas.connect(nas_env["QNAP_SSH_HOST"], username=nas_env["QNAP_SSH_USERNAME"],
            password=nas_env["QNAP_SSH_PASSWORD"], timeout=15)

def qnap(cmd):
    _, out, err = nas.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

# Read current exports
exports, _ = qnap("cat /etc/exports")
print("Current exports (relevant lines):")
for line in exports.splitlines():
    if "Multimedia" in line or "NFSv" in line and "Multi" in line:
        print(" ", line[:120])

# Check if PROXMOX_HOST already has rw access to Multimedia
if PROXMOX_IP in exports and "Multimedia" in exports:
    # Find the relevant lines and check
    for line in exports.splitlines():
        if "Multimedia" in line and PROXMOX_IP in line:
            print(f"\nProxmox already in Multimedia export: {line[:120]}")

# We need to add PROXMOX_HOST(rw,...) to both Multimedia export lines.
# The exports file has two relevant lines:
# 1. "/share/CACHEDEV1_DATA/Multimedia" *(ro,...) <NAS_CLIENT_IP>(rw,...) ...
# 2. "/share/NFSv=4/Multimedia" *(ro,...) <NAS_CLIENT_IP>(rw,...) ...
# 
# For each line that has Multimedia and does NOT already have our IP, add it.

new_exports_lines = []
changed = False
for line in exports.splitlines():
    if ("Multimedia" in line and
            PROXMOX_IP not in line and
            ("CACHEDEV" in line or "NFSv=4/Multimedia" in line)):
        # Grab the options from the <NAS_CLIENT_IP> entry as a template
        m = re.search(r'192\.168\.86\.64\(([^)]+)\)', line)
        if m:
            opts = m.group(1)
        else:
            opts = NFS_OPTS
        new_entry = f" {PROXMOX_IP}({opts})"
        line = line.rstrip() + new_entry
        print(f"\nAdded to export line: {line[:140]}")
        changed = True
    new_exports_lines.append(line)

if not changed:
    print("\n⚠️  Could not find Multimedia export lines to patch, or Proxmox already present")
else:
    new_exports = "\n".join(new_exports_lines) + "\n"
    # Write back via sftp
    sftp = nas.open_sftp()
    with sftp.open("/etc/exports", "w") as f:
        f.write(new_exports)
    sftp.close()
    print("✅ /etc/exports updated")

    # Reload exports on QNAP
    out_rel, err_rel = qnap("exportfs -ra 2>&1")
    print(f"exportfs -ra: {out_rel or err_rel or 'ok'}")

    # Verify
    out_v, _ = qnap("exportfs -v 2>/dev/null | grep -i Multimedia | head -6")
    print(f"Verified exports:\n{out_v}")

nas.close()

# ── Proxmox: remount the NFS share ───────────────────────────────────────────
print("\n=== Remounting NFS on Proxmox ===")
prox = paramiko.SSHClient()
prox.set_missing_host_key_policy(paramiko.AutoAddPolicy())
prox.connect(home_env["PROXMOX_HOST"], username="root", password=home_env["PROXMOX_PASSWORD"])

def host(cmd):
    _, out, err = prox.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

def pct(vmid, cmd):
    _, out, err = prox.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# Unmount and remount
out1, err1 = host("umount /mnt/pve/qnap-nfs-Multimedia 2>&1")
print(f"umount: {err1 or out1 or 'ok'}")
time.sleep(2)
out2, err2 = host("mount /mnt/pve/qnap-nfs-Multimedia 2>&1")
print(f"mount: {err2 or out2 or 'ok'}")
time.sleep(2)

# Test write from Proxmox host
out3, err3 = host("touch /mnt/pve/qnap-nfs-Multimedia/Videos/movies/.pve_test 2>&1 && rm -f /mnt/pve/qnap-nfs-Multimedia/Videos/movies/.pve_test && echo HOST_WRITABLE")
print(f"Host write test: {out3 or err3}")

# Restart LXCs so they pick up the remounted NFS
print("\n=== Restarting *arr LXCs ===")
for vmid, name in [("107","radarr"), ("111","sonarr"), ("113","readarr"), ("109","qbt")]:
    host(f"pct stop {vmid} 2>/dev/null; sleep 2; pct start {vmid} 2>/dev/null")
    print(f"  CT{vmid} {name} restarted")
time.sleep(12)

# Verify write from inside containers
print("\n=== Container write tests ===")
for vmid, path, name in [("107","/data/movies","radarr"), ("111","/data/television","sonarr")]:
    out, _ = pct(vmid, f"touch {path}/.write_test 2>&1 && rm -f {path}/.write_test && echo WRITABLE || echo READONLY")
    print(f"  {name} {path}: {out}")

# ── Set root folders ──────────────────────────────────────────────────────────
print("\n=== Setting root folders ===")
time.sleep(5)

def add_root_folder(ip, port, api_ver, key, path, name):
    try:
        r = requests.get(f"http://{ip}:{port}/api/{api_ver}/rootfolder",
                         headers={"X-Api-Key": key}, timeout=10)
        existing = [x["path"] for x in r.json()]
        if path in existing:
            print(f"  {name}: already set ✅")
            return
        r2 = requests.post(f"http://{ip}:{port}/api/{api_ver}/rootfolder",
                           headers={"X-Api-Key": key, "Content-Type": "application/json"},
                           data=json.dumps({"path": path}), timeout=10)
        if r2.status_code in (200, 201):
            print(f"  {name}: {path} ✅")
        else:
            print(f"  {name}: ❌ {r2.status_code} {r2.text[:200]}")
    except Exception as e:
        print(f"  {name}: ERROR {e}")

add_root_folder(RADARR_IP,  7878, "v3", RADARR_KEY,  "/data/movies",     "Radarr")
add_root_folder(SONARR_IP,  8989, "v3", SONARR_KEY,  "/data/television", "Sonarr")

prox.close()
print("\nDone.")
