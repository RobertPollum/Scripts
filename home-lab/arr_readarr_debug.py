"""
Debug why /data/books is read-only in Readarr but /data/movies is rw in Radarr.
Check actual NFS mount options and UID mapping differences.
"""
import paramiko, requests, json, time
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

prox = paramiko.SSHClient()
prox.set_missing_host_key_policy(paramiko.AutoAddPolicy())
prox.connect(home_env["PROXMOX_HOST"], username="root", password=home_env["PROXMOX_PASSWORD"])

def host(cmd):
    _, out, err = prox.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

def pct(vmid, cmd):
    _, out, err = prox.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# ── Compare mount options between working (Radarr/movies) vs broken (Readarr/books) ──
print("=== Mount comparison ===")
for vmid, path, name in [("107", "/data/movies", "Radarr-movies"), 
                          ("111", "/data/television", "Sonarr-tv"),
                          ("113", "/data/books", "Readarr-books")]:
    out, _ = pct(vmid, f"cat /proc/mounts | grep '{path}'")
    print(f"\n{name}:")
    print(f"  {out[:120]}")

# ── Check actual write permission ────────────────────────────────────────────
print("\n=== Write tests ===")
for vmid, path, name in [("107", "/data/movies", "Radarr"), 
                          ("113", "/data/books", "Readarr")]:
    out, _ = pct(vmid, f"touch {path}/.test 2>&1 && rm -f {path}/.test && echo OK")
    print(f"  {name}: {out}")

# ── Check LXC config differences ─────────────────────────────────────────────
print("\n=== LXC conf diffs ===")
for vmid, name in [("107","radarr"), ("113","readarr")]:
    conf, _ = host(f"cat /etc/pve/lxc/{vmid}.conf")
    print(f"\n{name} CT{vmid}:")
    for l in conf.splitlines():
        if l.startswith("mp") or "unprivileged" in l or "features" in l:
            print(f"  {l}")

# ── Key difference: unprivileged vs privileged LXC ────────────────────────────
# Unprivileged LXC maps UID 0 inside to UID 100000 outside (subuid mapping)
# NFS sees UID 100000, which gets squashed or is not UID 1000 (NAS owner)
# Privileged LXC: UID 0 inside = UID 0 outside → no_root_squash allows writes
# Solution for unprivileged: NFS mount needs to be done at host level and bind-mounted

# Check if the Proxmox host itself can write to the NFS path:
print("\n=== Host write tests ===")
for path in ["/mnt/pve/qnap-nfs-Multimedia/Videos/movies",
             "/mnt/pve/qnap-nfs-Multimedia/Videos/television",
             "/mnt/pve/qnap-nfs-Multimedia/Videos/books"]:
    out, err = host(f"touch {path}/.test 2>&1 && rm -f {path}/.test && echo WRITABLE || echo '{err}'")
    print(f"  {path}: {out}")

# ── Find QNAP web port ────────────────────────────────────────────────────────
print("\n=== QNAP web port ===")
for port in [8080, 443, 8443, 80]:
    import socket
    try:
        s = socket.create_connection((os.environ["NAS_HOST"], port), timeout=2)
        s.close()
        print(f"  Port {port}: OPEN")
    except Exception:
        print(f"  Port {port}: closed")

prox.close()
