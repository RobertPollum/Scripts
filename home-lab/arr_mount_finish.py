"""
Finish NAS mount setup:
1. Add PROXMOX_HOST rw to CACHEDEV1_DATA/Multimedia export (the actual mount path)
2. Create Videos/books dir on NAS
3. Add books bind mount to Readarr (CT113)
4. Set Readarr root folder
5. Verify everything end-to-end
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

RADARR_IP  = os.environ["RADARR_IP"];   RADARR_KEY  = os.environ["RADARR_API_KEY"]
SONARR_IP  = os.environ["SONARR_IP"];  SONARR_KEY  = os.environ["SONARR_API_KEY"]
READARR_IP = os.environ["READARR_IP"];  READARR_KEY = os.environ["READARR_API_KEY"]
PROXMOX_IP = os.environ["PROXMOX_HOST"]
NAS_PASS   = nas_env["QNAP_SSH_PASSWORD"]

# ── QNAP: fix CACHEDEV1 export + create books dir ────────────────────────────
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

# Read current exports
exports_raw, _ = qnap("cat /etc/exports")
print("=== Current /etc/exports ===")
for l in exports_raw.splitlines():
    if "Multimedia" in l or "CACHEDEV" in l:
        print(" ", l[:120])

# Patch CACHEDEV1_DATA/Multimedia if Proxmox not in it
new_lines = []
changed = False
for line in exports_raw.splitlines():
    if ("CACHEDEV1_DATA/Multimedia" in line and PROXMOX_IP not in line):
        m = re.search(r'192\.168\.86\.64\(([^)]+)\)', line)
        opts = m.group(1) if m else "sec=sys,rw,async,wdelay,insecure,no_subtree_check,no_root_squash"
        line = line.rstrip() + f" {PROXMOX_IP}({opts})"
        print(f"\nPatching CACHEDEV line: ...{line[-100:]}")
        changed = True
    new_lines.append(line)

if changed:
    new_exports = "\n".join(new_lines) + "\n"
    chan = nas.get_transport().open_session()
    chan.exec_command("cat > /tmp/exports_v2")
    chan.sendall(new_exports.encode())
    chan.shutdown_write()
    chan.recv_exit_status()
    out1 = qnap_sudo("cp /tmp/exports_v2 /etc/exports && exportfs -ra && echo OK")
    print(f"Updated CACHEDEV export: {out1}")
else:
    print("CACHEDEV1 export already has Proxmox IP or not found")

# Create books dir on NAS (now writable via NFSv4 export)
print("\n=== Creating Videos/books on NAS ===")
out2, err2 = qnap("mkdir -p /share/CACHEDEV1_DATA/Multimedia/Videos/books 2>&1 && echo OK")
print(f"mkdir books: {out2 or err2}")

nas.close()

# ── Proxmox: remount and verify ───────────────────────────────────────────────
prox = paramiko.SSHClient()
prox.set_missing_host_key_policy(paramiko.AutoAddPolicy())
prox.connect(home_env["PROXMOX_HOST"], username="root", password=home_env["PROXMOX_PASSWORD"])

def host(cmd):
    _, out, err = prox.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

def pct(vmid, cmd):
    _, out, err = prox.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# Remount to pick up updated CACHEDEV export
print("\n=== Remounting NFS on Proxmox ===")
host("umount /mnt/pve/qnap-nfs-Multimedia 2>/dev/null; sleep 2")
out3, err3 = host(f"mount -t nfs4 {os.environ['NAS_HOST']}:/Multimedia /mnt/pve/qnap-nfs-Multimedia -o rw,vers=4.1 2>&1")
print(f"Remount: {out3 or err3 or 'ok'}")
time.sleep(3)

# Verify books dir exists now
out4, _ = host("ls /mnt/pve/qnap-nfs-Multimedia/Videos/ | grep books")
print(f"books dir visible on Proxmox: {out4 or '(not found)'}")

# Create it directly from Proxmox if not there
if not out4:
    out5, err5 = host("mkdir -p /mnt/pve/qnap-nfs-Multimedia/Videos/books 2>&1 && echo OK")
    print(f"mkdir from Proxmox: {out5 or err5}")

# ── Add books bind mount to Readarr (CT113) ───────────────────────────────────
print("\n=== Adding books bind mount to Readarr ===")
conf_path = "/etc/pve/lxc/113.conf"
conf_out, _ = host(f"cat {conf_path}")

# Check if already there
if "/data/books" in conf_out:
    print("  Already has books mount")
else:
    existing_mps = [l for l in conf_out.splitlines() if l.startswith("mp")]
    next_idx = len(existing_mps)
    new_line = f"mp{next_idx}: /mnt/pve/qnap-nfs-Multimedia/Videos/books,mp=/data/books"
    new_conf = conf_out.rstrip() + "\n" + new_line + "\n"

    sftp = prox.open_sftp()
    with sftp.open("/tmp/lxc_113_books.conf", "w") as f:
        f.write(new_conf)
    sftp.close()
    host(f"pct stop 113 2>/dev/null; sleep 3; cp /tmp/lxc_113_books.conf {conf_path}")
    out6, err6 = host("pct start 113 2>&1")
    print(f"  CT113 start: {err6 or out6 or 'ok'}")
    time.sleep(8)
    ls_out, _ = pct("113", "ls /data/books 2>/dev/null && echo EXISTS || echo MISSING")
    print(f"  /data/books inside CT113: {ls_out}")

# Also add books mount to qBT (CT109)
print("\n=== Adding books bind mount to qBT ===")
conf_path_109 = "/etc/pve/lxc/109.conf"
conf_out_109, _ = host(f"cat {conf_path_109}")
if "/data/books" in conf_out_109:
    print("  qBT already has books mount")
else:
    existing_mps = [l for l in conf_out_109.splitlines() if l.startswith("mp")]
    next_idx = len(existing_mps)
    new_line = f"mp{next_idx}: /mnt/pve/qnap-nfs-Multimedia/Videos/books,mp=/data/books"
    new_conf_109 = conf_out_109.rstrip() + "\n" + new_line + "\n"
    sftp = prox.open_sftp()
    with sftp.open("/tmp/lxc_109_books.conf", "w") as f:
        f.write(new_conf_109)
    sftp.close()
    host("pct stop 109 2>/dev/null; sleep 3; cp /tmp/lxc_109_books.conf /etc/pve/lxc/109.conf")
    out7, err7 = host("pct start 109 2>&1")
    print(f"  CT109 start: {err7 or out7 or 'ok'}")
    time.sleep(8)

# ── Set Readarr root folder ───────────────────────────────────────────────────
print("\n=== Setting Readarr root folder ===")
time.sleep(5)
try:
    r = requests.get(f"http://{READARR_IP}:8787/api/v1/rootfolder",
                     headers={"X-Api-Key": READARR_KEY}, timeout=10)
    existing = [x["path"] for x in r.json()]
    if "/data/books" in existing:
        print("  Readarr: /data/books already set ✅")
    else:
        r2 = requests.post(f"http://{READARR_IP}:8787/api/v1/rootfolder",
                           headers={"X-Api-Key": READARR_KEY, "Content-Type": "application/json"},
                           data=json.dumps({"path": "/data/books"}), timeout=10)
        print(f"  Readarr: {r2.status_code} {'✅' if r2.status_code in (200,201) else r2.text[:200]}")
except Exception as e:
    print(f"  Readarr: {e}")

# ── Final summary ─────────────────────────────────────────────────────────────
print("\n=== Final verification ===")
for vmid, path, name in [("107","/data/movies","Radarr"),
                          ("111","/data/television","Sonarr"),
                          ("113","/data/books","Readarr"),
                          ("109","/data/movies","qBT-movies"),
                          ("109","/data/television","qBT-tv")]:
    out, _ = pct(vmid, f"ls {path} 2>/dev/null | wc -l")
    writable, _ = pct(vmid, f"touch {path}/.w 2>/dev/null && rm -f {path}/.w && echo rw || echo ro")
    print(f"  CT{vmid} {name} {path}: {out} items, {writable}")

print("\n=== Root folders ===")
for ip, port, ver, key, name in [
    (RADARR_IP, 7878, "v3", RADARR_KEY, "Radarr"),
    (SONARR_IP, 8989, "v3", SONARR_KEY, "Sonarr"),
    (READARR_IP, 8787, "v1", READARR_KEY, "Readarr"),
]:
    try:
        r = requests.get(f"http://{ip}:{port}/api/{ver}/rootfolder",
                         headers={"X-Api-Key": key}, timeout=10)
        folders = [x["path"] for x in r.json()]
        print(f"  {name}: {folders}")
    except Exception as e:
        print(f"  {name}: ERROR {e}")

prox.close()
print("\nDone.")
