"""
Fix CT113/CT109 (remove books bind mount, restart), check NFS write perms,
set root folders in all *arr apps, and set UID mapping if needed.
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

# ── Step 1: Remove books mount from CT113 and CT109 ──────────────────────────
print("=== Fixing CT113 and CT109 configs ===")
for vmid in ["113", "109"]:
    conf_path = f"/etc/pve/lxc/{vmid}.conf"
    conf_out, _ = host(f"cat {conf_path}")
    clean_lines = [l for l in conf_out.splitlines() if "books" not in l.lower()]
    new_conf = "\n".join(clean_lines) + "\n"

    sftp = c.open_sftp()
    with sftp.open(f"/tmp/lxc_{vmid}_fix.conf", "w") as f:
        f.write(new_conf)
    sftp.close()
    host(f"cp /tmp/lxc_{vmid}_fix.conf {conf_path}")

    mp_lines, _ = host(f"grep '^mp' {conf_path}")
    print(f"  CT{vmid} mounts: {mp_lines or '(none)'}")

    out_start, err_start = host(f"pct start {vmid} 2>&1")
    print(f"  CT{vmid} start: {err_start or out_start or 'ok'}")

time.sleep(10)

# ── Step 2: Check NFS write perms from inside each container ─────────────────
print("\n=== NFS write test ===")
# NAS dirs owned by UID 1000, perms 777 — should be writable by anyone
for vmid, path, name in [("107", "/data/movies", "radarr"),
                          ("111", "/data/television", "sonarr"),
                          ("113", "/data/movies", "readarr"),   # readarr has no mount yet
                          ("109", "/data/movies", "qbt")]:
    out, _ = pct(vmid, f"touch {path}/.write_test 2>&1 && rm -f {path}/.write_test && echo WRITABLE || echo READONLY")
    print(f"  {name} {path}: {out}")

# ── Step 3: Check what UID the *arr services run as ───────────────────────────
print("\n=== Service UIDs ===")
for vmid, svc in [("107","radarr"), ("111","sonarr"), ("113","readarr"), ("109","qbittorrent-nox")]:
    uid, _ = pct(vmid, f"id $(systemctl show {svc} -p User --value 2>/dev/null || echo root) 2>/dev/null")
    print(f"  CT{vmid} {svc}: {uid}")

# ── Step 4: Check if NFS mount is actually rw inside containers ───────────────
print("\n=== Mount options inside containers ===")
for vmid in ["107", "111"]:
    out, _ = pct(vmid, "mount | grep '/data/'")
    print(f"  CT{vmid}: {out}")

# ── Step 5: Set root folders ──────────────────────────────────────────────────
print("\n=== Setting root folders ===")

def add_root_folder(ip, port, api_ver, key, path, name):
    try:
        r = requests.get(f"http://{ip}:{port}/api/{api_ver}/rootfolder",
                         headers={"X-Api-Key": key}, timeout=10)
        existing = [x["path"] for x in r.json()]
        if path in existing:
            print(f"  {name}: {path} already set ✅")
            return True
        r2 = requests.post(f"http://{ip}:{port}/api/{api_ver}/rootfolder",
                           headers={"X-Api-Key": key, "Content-Type": "application/json"},
                           data=json.dumps({"path": path}), timeout=10)
        if r2.status_code in (200, 201):
            print(f"  {name}: {path} ✅")
            return True
        else:
            print(f"  {name}: {path} ❌ {r2.status_code} {r2.text[:200]}")
            return False
    except Exception as e:
        print(f"  {name}: ERROR {e}")
        return False

add_root_folder(RADARR_IP,  7878, "v3", RADARR_KEY,  "/data/movies",     "Radarr")
add_root_folder(SONARR_IP,  8989, "v3", SONARR_KEY,  "/data/television", "Sonarr")
# Readarr — mount not yet added, skip for now
# add_root_folder(READARR_IP, 8787, "v1", READARR_KEY, "/data/books",    "Readarr")

# ── Step 6: Verify qBT categories ────────────────────────────────────────────
print("\n=== qBT categories ===")
s2 = requests.Session()
_env_qbittorrent_ip = os.environ["QBITTORRENT_IP"]
s2.post(f"http://{_env_qbittorrent_ip}:8090/api/v2/auth/login",
        data={"username": "admin", "password": os.environ["QBITTORRENT_PASSWORD"]}, timeout=5)
cats = s2.get(f"http://{_env_qbittorrent_ip}:8090/api/v2/torrents/categories", timeout=5).json()
for name, info in cats.items():
    print(f"  {name}: savePath={info.get('savePath')}")

# ── Step 7: Update qBT download client categories in Radarr/Sonarr ───────────
# Make sure qBT clients in Radarr/Sonarr use the right category
print("\n=== Updating qBT client categories in Radarr/Sonarr ===")
for ip, port, api_ver, key, app_name, cat_field, cat_val in [
    (RADARR_IP,  7878, "v3", RADARR_KEY,  "Radarr",  "movieCategory",  "radarr"),
    (SONARR_IP,  8989, "v3", SONARR_KEY,  "Sonarr",  "tvCategory",     "sonarr"),
    (READARR_IP, 8787, "v1", READARR_KEY, "Readarr", "musicCategory",  "readarr"),
]:
    try:
        clients = requests.get(f"http://{ip}:{port}/api/{api_ver}/downloadclient",
                               headers={"X-Api-Key": key}, timeout=10).json()
        qbt = next((x for x in clients if x.get("implementation") == "QBittorrent"), None)
        if not qbt:
            print(f"  {app_name}: no qBT client found")
            continue
        # Check current category field
        for field in qbt.get("fields", []):
            if field["name"] == cat_field:
                print(f"  {app_name} {cat_field}={field.get('value')!r} → setting to {cat_val!r}")
                field["value"] = cat_val
        qbt.pop("id", None) if False else None  # keep id for PUT
        r3 = requests.put(f"http://{ip}:{port}/api/{api_ver}/downloadclient/{qbt['id']}",
                          headers={"X-Api-Key": key, "Content-Type": "application/json"},
                          data=json.dumps(qbt), timeout=10)
        print(f"    PUT: {r3.status_code} {'✅' if r3.status_code in (200,202) else r3.text[:100]}")
    except Exception as e:
        print(f"  {app_name}: ERROR {e}")

c.close()
print("\nDone.")
