"""
Add Proxmox IP to QNAP NFS Multimedia export using echo/sed via SSH exec
(SFTP write to /etc/exports is blocked on QNAP).
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
PROXMOX_IP = os.environ["PROXMOX_HOST"]

# ── QNAP ──────────────────────────────────────────────────────────────────────
print("=== Connecting to QNAP ===")
nas = paramiko.SSHClient()
nas.set_missing_host_key_policy(paramiko.AutoAddPolicy())
nas.connect(nas_env["QNAP_SSH_HOST"], username=nas_env["QNAP_SSH_USERNAME"],
            password=nas_env["QNAP_SSH_PASSWORD"], timeout=15)

def qnap(cmd):
    _, out, err = nas.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

# Read current exports
exports_raw, _ = qnap("cat /etc/exports")

# Parse and rebuild with Proxmox IP added to Multimedia lines
new_lines = []
changed = False
for line in exports_raw.splitlines():
    if ("Multimedia" in line and PROXMOX_IP not in line and
            ("CACHEDEV" in line or "NFSv=4/Multimedia" in line)):
        # Get options from <NAS_CLIENT_IP> entry as template for rw access
        m = re.search(r'192\.168\.86\.64\(([^)]+)\)', line)
        opts = m.group(1) if m else "sec=sys,rw,async,wdelay,insecure,no_subtree_check,no_root_squash"
        line = line.rstrip() + f" {PROXMOX_IP}({opts})"
        print(f"Patched: ...{line[-80:]}")
        changed = True
    new_lines.append(line)

if not changed:
    print("No changes needed or already patched.")
else:
    new_exports = "\n".join(new_lines) + "\n"
    # Write using tee via SSH (avoids SFTP permission issues)
    # Escape for shell: write to /tmp first then cp with sudo
    sftp_tmp = "/tmp/exports_new"
    # Use heredoc via channel
    chan = nas.get_transport().open_session()
    chan.exec_command(f"cat > {sftp_tmp}")
    chan.sendall(new_exports.encode())
    chan.shutdown_write()
    exit_status = chan.recv_exit_status()
    print(f"Write to /tmp: exit={exit_status}")

    # cp /tmp/exports_new /etc/exports  
    out_cp, err_cp = qnap(f"cp {sftp_tmp} /etc/exports 2>&1 && echo OK")
    print(f"cp to /etc/exports: {out_cp or err_cp}")

    # Reload
    out_r, err_r = qnap("exportfs -ra 2>&1")
    print(f"exportfs -ra: {out_r or err_r or 'ok'}")

    # Verify the change
    out_v, _ = qnap(f"exportfs -v 2>/dev/null | grep -i Multimedia | grep '{PROXMOX_IP}'")
    print(f"Verify (Proxmox in exports): {out_v or '(not found yet)'}")

nas.close()

# ── Proxmox: remount ──────────────────────────────────────────────────────────
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

out1, err1 = host("umount /mnt/pve/qnap-nfs-Multimedia 2>&1; sleep 2; mount /mnt/pve/qnap-nfs-Multimedia 2>&1")
print(f"Remount: {out1 or err1 or 'ok'}")
time.sleep(3)

# Test write from host
out2, err2 = host("touch /mnt/pve/qnap-nfs-Multimedia/Videos/movies/.pve_test 2>&1 && rm -f /mnt/pve/qnap-nfs-Multimedia/Videos/movies/.pve_test && echo WRITABLE")
print(f"Host write test: {out2 or err2}")

if "WRITABLE" not in out2:
    print("⚠️  Still read-only — check if exportfs -ra applied correctly on QNAP")
    prox.close()
    exit(1)

# Restart *arr LXCs to pick up remounted share
print("\n=== Restarting LXCs ===")
for vmid, name in [("107","radarr"), ("111","sonarr"), ("109","qbt")]:
    host(f"pct stop {vmid} 2>/dev/null; sleep 2; pct start {vmid} 2>/dev/null")
    print(f"  CT{vmid} {name} restarted")
time.sleep(12)

# Verify write from containers
print("\n=== Container write tests ===")
for vmid, path, name in [("107","/data/movies","radarr"), ("111","/data/television","sonarr"), ("109","/data/movies","qbt")]:
    out, _ = pct(vmid, f"touch {path}/.write_test 2>&1 && rm -f {path}/.write_test && echo WRITABLE || echo READONLY")
    print(f"  {name} {path}: {out}")

# Set root folders
print("\n=== Setting root folders ===")
time.sleep(3)

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

add_root_folder(RADARR_IP, 7878, "v3", RADARR_KEY, "/data/movies",     "Radarr")
add_root_folder(SONARR_IP, 8989, "v3", SONARR_KEY, "/data/television", "Sonarr")

prox.close()
print("\nDone.")
