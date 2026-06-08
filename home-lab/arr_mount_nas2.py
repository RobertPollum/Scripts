"""
Fix LXC bind mounts (correct mp syntax) and configure root folders.
Also handle read-only NAS by creating dirs via qBT container after mount.

Proxmox LXC mp syntax: mp0: /host/path,mp=/container/path
"""
import paramiko, os, requests, json, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

NAS_BASE   = "/mnt/pve/qnap-nfs-Multimedia/Videos"
NAS_MOVIES = f"{NAS_BASE}/movies"
NAS_TV     = f"{NAS_BASE}/television"
NAS_BOOKS  = f"{NAS_BASE}/books"

RADARR_IP  = os.environ["RADARR_IP"];   RADARR_KEY  = os.environ["RADARR_API_KEY"]
SONARR_IP  = os.environ["SONARR_IP"];  SONARR_KEY  = os.environ["SONARR_API_KEY"]
READARR_IP = os.environ["READARR_IP"];  READARR_KEY = os.environ["READARR_API_KEY"]

# VMID → list of (host_path, container_mp_path)
LXC_MOUNTS = {
    "107": [( NAS_MOVIES, "/data/movies"     )],
    "111": [( NAS_TV,     "/data/television" )],
    "113": [( NAS_BOOKS,  "/data/books"      )],
    "109": [( NAS_MOVIES, "/data/movies"     ),
            ( NAS_TV,     "/data/television" ),
            ( NAS_BOOKS,  "/data/books"      )],
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

# ── Step 1: Check NAS write permissions and create dirs ───────────────────────
print("=== NAS directory check ===")
out, _ = host(f"ls {NAS_BASE!r} 2>/dev/null")
print(f"  Existing dirs in Videos/: {out or '(empty or missing)'}")

# Check if NAS root is writable
out2, err2 = host(f"touch /mnt/pve/qnap-nfs-Multimedia/.write_test 2>&1 && rm -f /mnt/pve/qnap-nfs-Multimedia/.write_test && echo WRITABLE || echo READ_ONLY")
print(f"  NAS writable: {out2}")

# Try creating Videos dir first if needed
host(f"mkdir -p {NAS_BASE!r} 2>/dev/null || true")
for d in [NAS_MOVIES, NAS_TV]:
    out3, err3 = host(f"mkdir -p {d!r} 2>&1")
    print(f"  mkdir {d}: {err3 or 'ok'}")

# books: skip if read-only, we can add it later
out4, err4 = host(f"mkdir -p {NAS_BOOKS!r} 2>&1")
print(f"  mkdir books: {err4 or 'ok'}")
BOOKS_OK = "cannot" not in err4 and "Read-only" not in err4

if not BOOKS_OK:
    print("  ⚠️  NAS is read-only for creating new dirs — books dir skipped")
    print("     Create 'Videos/books' on the QNAP manually if needed for Readarr")
    # Remove books from mounts
    LXC_MOUNTS["113"] = []
    LXC_MOUNTS["109"] = [(NAS_MOVIES, "/data/movies"), (NAS_TV, "/data/television")]

# ── Step 2: Remove bad mp lines added previously and rewrite correctly ────────
print("\n=== Fixing LXC configs ===")

for vmid, mounts in LXC_MOUNTS.items():
    conf_path = f"/etc/pve/lxc/{vmid}.conf"
    conf_out, _ = host(f"cat {conf_path}")

    # Remove any previously-added malformed mp lines
    clean_lines = [l for l in conf_out.splitlines()
                   if not (l.startswith("mp") and "qnap-nfs-Multimedia" in l)]

    # Build new correct mp entries
    # Find the next free mp index (accounting for existing valid mps)
    existing_valid = [l for l in clean_lines if l.startswith("mp")]
    next_idx = len(existing_valid)

    new_mp_lines = []
    for host_path, ct_path in mounts:
        new_mp_lines.append(f"mp{next_idx}: {host_path},mp={ct_path}")
        next_idx += 1

    new_conf = "\n".join(clean_lines + new_mp_lines) + "\n"

    # Write via SFTP
    sftp = c.open_sftp()
    with sftp.open(f"/tmp/lxc_{vmid}.conf", "w") as f:
        f.write(new_conf)
    sftp.close()

    # Validate before applying
    print(f"\n  CT{vmid} new mp lines: {new_mp_lines}")

    # Stop, replace config, start
    host(f"pct stop {vmid} 2>/dev/null; sleep 3; true")
    time.sleep(5)
    _, cp_err = host(f"cp /tmp/lxc_{vmid}.conf {conf_path}")
    if cp_err:
        print(f"    config write error: {cp_err}")
        continue

    out_start, err_start = host(f"pct start {vmid} 2>&1")
    print(f"    start: {err_start or out_start or 'ok'}")
    time.sleep(8)

    # Verify mount inside container
    for _, ct_path in mounts:
        ls_out, _ = pct(vmid, f"ls {ct_path!r} 2>/dev/null && echo EXISTS || echo MISSING")
        print(f"    {ct_path}: {ls_out}")

# ── Step 3: Add root folders to *arr apps ─────────────────────────────────────
print("\n=== Setting root folders ===")

def add_root_folder(ip, port, api_ver, key, path, name):
    # Check if already exists
    r = requests.get(f"http://{ip}:{port}/api/{api_ver}/rootfolder",
                     headers={"X-Api-Key": key})
    existing = [x["path"] for x in r.json()]
    if path in existing:
        print(f"  {name}: {path} already set ✅")
        return
    r2 = requests.post(f"http://{ip}:{port}/api/{api_ver}/rootfolder",
                       headers={"X-Api-Key": key, "Content-Type": "application/json"},
                       data=json.dumps({"path": path}))
    if r2.status_code in (200, 201):
        print(f"  {name}: {path} ✅")
    else:
        print(f"  {name}: {path} ❌ {r2.status_code} {r2.text[:150]}")

time.sleep(3)
add_root_folder(RADARR_IP,  7878, "v3", RADARR_KEY,  "/data/movies",     "Radarr")
add_root_folder(SONARR_IP,  8989, "v3", SONARR_KEY,  "/data/television", "Sonarr")
if BOOKS_OK:
    add_root_folder(READARR_IP, 8787, "v1", READARR_KEY, "/data/books", "Readarr")

# ── Step 4: Set qBT default save path and verify categories ───────────────────
print("\n=== qBT preferences ===")
s2 = requests.Session()
_env_qbittorrent_ip = os.environ["QBITTORRENT_IP"]
s2.post(f"http://{_env_qbittorrent_ip}:8090/api/v2/auth/login",
        data={"username": "admin", "password": os.environ["QBITTORRENT_PASSWORD"]})
prefs = s2.get(f"http://{_env_qbittorrent_ip}:8090/api/v2/app/preferences").json()
print(f"  Current save_path: {prefs.get('save_path')}")

cats = s2.get(f"http://{_env_qbittorrent_ip}:8090/api/v2/torrents/categories").json()
print(f"  Categories: {json.dumps(cats, indent=2)}")

c.close()
print("\nDone.")
