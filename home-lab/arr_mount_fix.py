"""
Fix mount issues:
1. Check NFS permissions (why dirs are not writable)
2. Remove books mount from CT113 + CT109 (dir doesn't exist on NAS)
3. Fix NFS write permissions if needed
4. Restart CT113 + CT109 and set root folders
"""
import paramiko, os, requests, json, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

RADARR_IP  = os.environ["RADARR_IP"];   RADARR_KEY  = os.environ["RADARR_API_KEY"]
SONARR_IP  = os.environ["SONARR_IP"];  SONARR_KEY  = os.environ["SONARR_API_KEY"]
READARR_IP = os.environ["READARR_IP"];  READARR_KEY = os.environ["READARR_API_KEY"]
NAS_BASE   = "/mnt/pve/qnap-nfs-Multimedia/Videos"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def host(cmd):
    _, out, err = c.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

def pct(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# ── Step 1: Diagnose NFS permissions ─────────────────────────────────────────
print("=== NFS permission check ===")
out, _ = host(f"ls -la {NAS_BASE!r}")
print(out)

out2, _ = host(f"stat {NAS_BASE!r}")
print(out2)

# Check mount options (no_root_squash?)
out3, _ = host("cat /proc/mounts | grep qnap-nfs-Multimedia")
print("Mount options:", out3)

# Try writing as root
out4, err4 = host(f"touch {NAS_BASE}/movies/.write_test 2>&1 && rm -f {NAS_BASE}/movies/.write_test && echo WRITABLE || echo '{err4}'")
print("Write test movies:", out4)

# ── Step 2: Remove books mount from CT113 and CT109 ──────────────────────────
print("\n=== Fixing CT113 and CT109 configs (remove books mount) ===")
for vmid in ["113", "109"]:
    conf_path = f"/etc/pve/lxc/{vmid}.conf"
    conf_out, _ = host(f"cat {conf_path}")

    # Remove any line referencing the books path
    clean_lines = [l for l in conf_out.splitlines()
                   if "books" not in l.lower()]
    new_conf = "\n".join(clean_lines) + "\n"

    sftp = c.open_sftp()
    with sftp.open(f"/tmp/lxc_{vmid}_fix.conf", "w") as f:
        f.write(new_conf)
    sftp.close()

    host(f"cp /tmp/lxc_{vmid}_fix.conf {conf_path}")
    print(f"  CT{vmid} conf updated. Remaining mp lines:")
    out5, _ = host(f"grep '^mp' {conf_path}")
    print(f"    {out5 or '(none)'}")

    out_start, err_start = host(f"pct start {vmid} 2>&1")
    print(f"  CT{vmid} start: {err_start or out_start or 'ok'}")
    time.sleep(8)

# ── Step 3: Check if NFS needs no_root_squash fix or chmod ───────────────────
print("\n=== NFS write test after start ===")
# Try from Radarr container
out6, err6 = pct("107", "touch /data/movies/.write_test 2>&1 && rm -f /data/movies/.write_test && echo WRITABLE || echo READONLY")
print(f"  Radarr /data/movies: {out6}")
out7, err7 = pct("111", "touch /data/television/.write_test 2>&1 && rm -f /data/television/.write_test && echo WRITABLE || echo READONLY")
print(f"  Sonarr /data/television: {out7}")

# Check owner/perms on the NAS dirs
out8, _ = host(f"ls -lan {NAS_BASE!r}")
print(f"\nNAS dir ownership:\n{out8}")

# ── Step 4: Fix NFS permissions if needed ────────────────────────────────────
# The NFS export likely has root_squash (root on client → nobody on server)
# Solutions:
# a) Re-export with no_root_squash on QNAP
# b) chmod 777 the dirs from an account that IS the owner
# c) Create a dedicated media user with matching UID/GID in all containers

# Check what UID owns the NAS dirs
out9, _ = host(f"stat -c '%u %g %a' {NAS_BASE}/movies {NAS_BASE}/television 2>/dev/null")
print(f"\nOwner UID/GID/perms: {out9}")

# Check what UID *arr runs as
for vmid, name in [("107","radarr"), ("111","sonarr"), ("113","readarr"), ("109","qbt")]:
    try:
        ou, _ = pct(vmid, f"id $(ps aux | grep -E '{name}|qbittorrent' | grep -v grep | head -1 | awk '{{print $1}}')")
        print(f"  {name} runs as: {ou}")
    except Exception:
        pass

c.close()
