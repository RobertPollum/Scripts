"""
Mount NAS share subdirs into *arr LXCs and qBT, configure root folders,
and set qBT per-category save paths.

NAS mount on Proxmox: /mnt/pve/qnap-nfs-Multimedia
Target structure:
  Multimedia/Videos/movies      → Radarr root folder, qBT movies category
  Multimedia/Videos/television  → Sonarr root folder, qBT television category
  Multimedia/Videos/books       → Readarr root folder (optional)

LXC mount points (inside each container):
  /data/movies      (Radarr, qBT)
  /data/television  (Sonarr, qBT)
  /data/books       (Readarr)
"""
import paramiko, os, requests, json, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

# ── Config ────────────────────────────────────────────────────────────────────
NAS_BASE   = "/mnt/pve/qnap-nfs-Multimedia/Videos"
NAS_MOVIES = f"{NAS_BASE}/movies"
NAS_TV     = f"{NAS_BASE}/television"
NAS_BOOKS  = f"{NAS_BASE}/books"

RADARR_IP  = os.environ["RADARR_IP"];   RADARR_KEY  = os.environ["RADARR_API_KEY"]
SONARR_IP  = os.environ["SONARR_IP"];  SONARR_KEY  = os.environ["SONARR_API_KEY"]
READARR_IP = os.environ["READARR_IP"];  READARR_KEY = os.environ["READARR_API_KEY"]

# VMID → (name, nas_paths_to_bind: [(host_path, container_path)])
LXC_MOUNTS = {
    "107": ("radarr",   [(NAS_MOVIES, "/data/movies")]),
    "111": ("sonarr",   [(NAS_TV,     "/data/television")]),
    "113": ("readarr",  [(NAS_BOOKS,  "/data/books")]),
    "109": ("qbt",      [(NAS_MOVIES, "/data/movies"),
                         (NAS_TV,     "/data/television"),
                         (NAS_BOOKS,  "/data/books")]),
}

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def host(cmd):
    _, out, err = c.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

def pct(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# ── Step 1: Create NAS subdirs if missing ─────────────────────────────────────
print("=== Creating NAS subdirs ===")
for d in [NAS_MOVIES, NAS_TV, NAS_BOOKS]:
    out, err = host(f"mkdir -p {d!r} && echo OK")
    print(f"  {d}: {out or err}")

# ── Step 2: Add bind mounts to LXC configs and restart ───────────────────────
print("\n=== Adding bind mounts to LXC configs ===")
for vmid, (name, mounts) in LXC_MOUNTS.items():
    conf_path = f"/etc/pve/lxc/{vmid}.conf"

    # Read current conf to find next mp index
    conf_out, _ = host(f"cat {conf_path}")
    existing_mps = [l for l in conf_out.splitlines() if l.startswith("mp")]
    next_idx = len(existing_mps)

    lines_to_add = []
    for host_path, ct_path in mounts:
        # Check if already mounted
        already = any(host_path in l or ct_path in l for l in conf_out.splitlines())
        if already:
            print(f"  {name} {ct_path}: already present, skipping")
            continue
        mp_line = f"mp{next_idx}: {host_path},{ct_path}"
        lines_to_add.append(mp_line)
        next_idx += 1

    if not lines_to_add:
        continue

    # Stop LXC, patch config, start
    print(f"  Stopping {name} (CT{vmid})...")
    host(f"pct stop {vmid} 2>/dev/null || true")
    time.sleep(5)

    for line in lines_to_add:
        out, err = host(f"echo {line!r} >> {conf_path}")
        print(f"    Added: {line}  ({err or 'ok'})")

    print(f"  Starting {name} (CT{vmid})...")
    out, err = host(f"pct start {vmid}")
    print(f"    {out or err or 'started'}")
    time.sleep(6)

    # Verify mount visible inside container
    for _, ct_path in mounts:
        ls_out, _ = pct(vmid, f"ls {ct_path} 2>/dev/null && echo EXISTS || echo MISSING")
        print(f"    {ct_path} inside container: {ls_out}")

# ── Step 3: Set qBT per-category save paths ───────────────────────────────────
print("\n=== qBT: setting category save paths ===")
_env_qbittorrent_ip = os.environ["QBITTORRENT_IP"]
QBT_BASE = f"http://{_env_qbittorrent_ip}:8090"

# Login (whitelist should bypass, but try anyway)
s = requests.Session()
s.post(f"{QBT_BASE}/api/v2/auth/login", data={"username": "admin", "password": os.environ["QBITTORRENT_PASSWORD"]})

for cat, save_path in [("radarr", "/data/movies"), ("sonarr", "/data/television"), ("readarr", "/data/books")]:
    # Try edit first (update existing), then add
    r = s.post(f"{QBT_BASE}/api/v2/torrents/editCategory",
               data={"category": cat, "savePath": save_path})
    if r.status_code != 200:
        r = s.post(f"{QBT_BASE}/api/v2/torrents/createCategory",
                   data={"category": cat, "savePath": save_path})
    print(f"  {cat} → {save_path}: {r.status_code}")

# Set default save path too
r2 = s.post(f"{QBT_BASE}/api/v2/app/setPreferences",
            data={"json": json.dumps({"save_path": "/data/movies"})})
print(f"  Default save path: {r2.status_code}")

# ── Step 4: Add root folders to *arr apps ─────────────────────────────────────
print("\n=== Setting root folders ===")

def add_root_folder(ip, port, api_ver, key, path):
    url = f"http://{ip}:{port}/api/{api_ver}/rootfolder"
    r = requests.post(url, headers={"X-Api-Key": key, "Content-Type": "application/json"},
                      data=json.dumps({"path": path}))
    return r.status_code, r.text[:200]

status, body = add_root_folder(RADARR_IP,  7878, "v3", RADARR_KEY,  "/data/movies")
print(f"  Radarr  /data/movies:      {status} {'✅' if status in (200,201) else body}")

status, body = add_root_folder(SONARR_IP,  8989, "v3", SONARR_KEY,  "/data/television")
print(f"  Sonarr  /data/television:  {status} {'✅' if status in (200,201) else body}")

status, body = add_root_folder(READARR_IP, 8787, "v1", READARR_KEY, "/data/books")
print(f"  Readarr /data/books:       {status} {'✅' if status in (200,201) else body}")

c.close()
print("\nDone.")
