"""
Mount Calibre Library from NAS into Readarr LXC and add it as a root folder.
NAS path: /Multimedia/Calibre Library  (NFS mounted on Proxmox at /mnt/pve/qnap-nfs-Multimedia)
"""
import paramiko, os, time, requests, json
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST  = os.environ["PROXMOX_HOST"]
PROXMOX_PASS  = os.environ["PROXMOX_PASSWORD"]
READARR_VMID  = "113"
READARR_IP    = os.environ["READARR_IP"]
READARR_KEY   = os.environ["READARR_API_KEY"]
BASE = f"http://{READARR_IP}:8787/api/v1"
HEADERS = {"X-Api-Key": READARR_KEY, "Content-Type": "application/json"}

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def host(cmd, timeout=15):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    return out.read().decode().strip(), err.read().decode().strip()

def pct(vmid, cmd, timeout=15):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}", timeout=timeout)
    return out.read().decode().strip(), err.read().decode().strip()

# ── 1. Check NAS mount on Proxmox ────────────────────────────────────────────
print("=== 1. Check NAS mount on Proxmox ===")
out, _ = host("ls /mnt/pve/qnap-nfs-Multimedia/")
print(f"  /mnt/pve/qnap-nfs-Multimedia/: {out}")

# Check if Calibre Library exists
out2, _ = host("ls '/mnt/pve/qnap-nfs-Multimedia/Calibre Library' 2>/dev/null | head -5 || echo NOT_FOUND")
print(f"  Calibre Library contents: {out2}")

# ── 2. Check current CT113 LXC config ────────────────────────────────────────
print("\n=== 2. Current CT113 config ===")
out3, _ = host("cat /etc/pve/lxc/113.conf")
print(out3)

# ── 3. Check existing root folders in Readarr ────────────────────────────────
print("\n=== 3. Existing Readarr root folders ===")
r = requests.get(f"{BASE}/rootFolder", headers=HEADERS, timeout=10)
print(f"  HTTP {r.status_code}")
for rf in r.json():
    print(f"  id={rf.get('id')} path={rf.get('path')} accessible={rf.get('accessible')}")

# ── 4. Add bind mount to CT113 ───────────────────────────────────────────────
print("\n=== 4. Adding Calibre Library bind mount to CT113 ===")

# Check if mp1 already exists
if "mp1:" in out3:
    print("  mp1 already set — skipping")
else:
    # LXC must be shut down to edit config, but we can use pct set on a running CT
    # pct set supports adding mountpoints on running containers (read-only config change,
    # mount takes effect after restart)
    out4, err4 = host("pct set 113 -mp1 '/mnt/pve/qnap-nfs-Multimedia/Calibre Library,mp=/data/calibre'")
    print(f"  pct set: {out4 or err4 or 'OK'}")

    # Restart CT113 so mount takes effect
    print("  Restarting CT113...")
    host("pct reboot 113", timeout=30)
    time.sleep(15)

# ── 5. Verify mount inside CT113 ─────────────────────────────────────────────
print("\n=== 5. Verify mount inside CT113 ===")
out5, _ = pct(READARR_VMID, "ls /data/calibre 2>/dev/null | head -5 || echo NOT_MOUNTED")
print(f"  /data/calibre: {out5}")

out6, _ = pct(READARR_VMID, "stat /data/calibre 2>&1 | head -3")
print(f"  stat: {out6}")

# ── 6. Add root folder to Readarr ────────────────────────────────────────────
print("\n=== 6. Adding /data/calibre as Readarr root folder ===")

# Check existing again
r2 = requests.get(f"{BASE}/rootFolder", headers=HEADERS, timeout=10).json()
if any(rf.get("path") == "/data/calibre" for rf in r2):
    print("  Already registered — skipping")
else:
    payload = {"name": "Calibre Library", "path": "/data/calibre", "defaultMetadataProfileId": 1, "defaultQualityProfileId": 1}
    r3 = requests.post(f"{BASE}/rootFolder", headers=HEADERS,
                       data=json.dumps(payload), timeout=10)
    print(f"  HTTP {r3.status_code}: {r3.text[:200]}")

# ── 7. Final state ───────────────────────────────────────────────────────────
print("\n=== 7. Final root folders ===")
for rf in requests.get(f"{BASE}/rootFolder", headers=HEADERS, timeout=10).json():
    print(f"  id={rf.get('id')} path={rf.get('path')} accessible={rf.get('accessible')} freeSpace={rf.get('freeSpace',0)//1024//1024//1024}GB")

c.close()
