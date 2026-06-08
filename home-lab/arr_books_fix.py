"""
Fix /data/books being read-only in Readarr.
The NFSv4 export has .93 rw, but CACHEDEV1_DATA export doesn't.
Proxmox mounts via NFSv4 path, so check what export is actually being used,
and also verify Readarr's mount is rw.
"""
import paramiko, re, requests, json, time
from pathlib import Path
import os
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

READARR_IP = os.environ["READARR_IP"]; READARR_KEY = os.environ["READARR_API_KEY"]
PROXMOX_IP = os.environ["PROXMOX_HOST"]
NAS_PASS   = nas_env["QNAP_SSH_PASSWORD"]

prox = paramiko.SSHClient()
prox.set_missing_host_key_policy(paramiko.AutoAddPolicy())
prox.connect(home_env["PROXMOX_HOST"], username="root", password=home_env["PROXMOX_PASSWORD"])

def host(cmd):
    _, out, err = prox.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

def pct(vmid, cmd):
    _, out, err = prox.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# ── Check what NFS path Readarr is actually using ────────────────────────────
print("=== Readarr mount details ===")
out, _ = pct("113", "mount | grep '/data/books'")
print(out)

# Check if the mount is showing as rw or ro
out2, _ = pct("113", "cat /proc/mounts | grep books")
print("proc/mounts:", out2)

# The mount is ro — check NFS export being used
print("\n=== NFS server export for books path ===")
nas = paramiko.SSHClient()
nas.set_missing_host_key_policy(paramiko.AutoAddPolicy())
nas.connect(nas_env["QNAP_SSH_HOST"], username=nas_env["QNAP_SSH_USERNAME"],
            password=NAS_PASS, timeout=15)

def qnap(cmd):
    _, out, err = nas.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

def qnap_sudo(cmd):
    chan = nas.get_transport().open_session()
    chan.exec_command(f"echo {NAS_PASS!r} | sudo -S {cmd} 2>&1")
    out = b""
    while True:
        chunk = chan.recv(4096)
        if not chunk:
            break
        out += chunk
    lines = [l for l in out.decode(errors="replace").strip().splitlines()
             if not l.startswith("Password:") and l]
    return "\n".join(lines)

exports, _ = qnap("cat /etc/exports")
print("Full exports:")
print(exports)

# Check the CACHEDEV1 Multimedia line
print(f"\n.93 in CACHEDEV1 line: {os.environ["PROXMOX_HOST"] in [l for l in exports.splitlines() if 'CACHEDEV1_DATA/Multimedia' in l][0] if any('CACHEDEV1_DATA/Multimedia' in l for l in exports.splitlines()) else 'LINE NOT FOUND'}")

# Patch CACHEDEV1_DATA/Multimedia if needed
new_lines = []
patched = False
for line in exports.splitlines():
    if "CACHEDEV1_DATA/Multimedia" in line and PROXMOX_IP not in line:
        m = re.search(r'192\.168\.86\.64\(([^)]+)\)', line)
        opts = m.group(1) if m else "sec=sys,rw,async,wdelay,insecure,no_subtree_check,no_root_squash"
        line = line.rstrip() + f" {PROXMOX_IP}({opts})"
        print(f"Patched CACHEDEV line")
        patched = True
    new_lines.append(line)

if patched:
    new_exports = "\n".join(new_lines) + "\n"
    chan = nas.get_transport().open_session()
    chan.exec_command("cat > /tmp/exports_v3")
    chan.sendall(new_exports.encode())
    chan.shutdown_write()
    chan.recv_exit_status()
    result = qnap_sudo("cp /tmp/exports_v3 /etc/exports && exportfs -ra && echo OK")
    print(f"Updated: {result}")
else:
    # Already has .93 in CACHEDEV line — the issue is the Proxmox mount went via NFSv4 path
    # which IS now rw for .93. The actual problem may be a stale mount.
    print("CACHEDEV line already has .93 — remount needed")

nas.close()

# ── Remount on Proxmox and restart CT113 ─────────────────────────────────────
print("\n=== Remounting and restarting CT113 ===")
host(f"umount /mnt/pve/qnap-nfs-Multimedia 2>/dev/null; sleep 2; mount -t nfs4 {os.environ['NAS_HOST']}:/Multimedia /mnt/pve/qnap-nfs-Multimedia -o rw,vers=4.1 2>&1")
time.sleep(3)

# Test books write from host
out3, err3 = host("touch /mnt/pve/qnap-nfs-Multimedia/Videos/books/.pve_test 2>&1 && rm -f /mnt/pve/qnap-nfs-Multimedia/Videos/books/.pve_test && echo WRITABLE")
print(f"Host books write: {out3 or err3}")

# Restart CT113
host("pct stop 113 2>/dev/null; sleep 3; pct start 113 2>/dev/null")
time.sleep(8)

out4, _ = pct("113", "touch /data/books/.w 2>/dev/null && rm -f /data/books/.w && echo WRITABLE || echo READONLY")
print(f"CT113 /data/books: {out4}")

# ── Set Readarr root folder ───────────────────────────────────────────────────
print("\n=== Setting Readarr root folder ===")
time.sleep(3)
try:
    r = requests.get(f"http://{READARR_IP}:8787/api/v1/rootfolder",
                     headers={"X-Api-Key": READARR_KEY}, timeout=10)
    existing = [x["path"] for x in r.json()]
    if "/data/books" in existing:
        print("  Already set ✅")
    else:
        r2 = requests.post(f"http://{READARR_IP}:8787/api/v1/rootfolder",
                           headers={"X-Api-Key": READARR_KEY, "Content-Type": "application/json"},
                           data=json.dumps({"path": "/data/books"}), timeout=10)
        print(f"  {r2.status_code} {'✅' if r2.status_code in (200,201) else r2.text[:200]}")
except Exception as e:
    print(f"  ERROR {e}")

prox.close()
