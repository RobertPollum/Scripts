"""Verify QNAP export change took effect and remount on Proxmox."""
import paramiko, time, requests, json
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

# ── Check QNAP exports now ────────────────────────────────────────────────────
nas = paramiko.SSHClient()
nas.set_missing_host_key_policy(paramiko.AutoAddPolicy())
nas.connect(nas_env["QNAP_SSH_HOST"], username=nas_env["QNAP_SSH_USERNAME"],
            password=nas_env["QNAP_SSH_PASSWORD"], timeout=15)

def qnap(cmd):
    _, out, err = nas.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

print("=== /etc/exports now ===")
out, _ = qnap("cat /etc/exports")
print(out[:800])

proxmox_in_exports = os.environ["PROXMOX_HOST"] in out
print(f"\nProxmox .93 in exports: {proxmox_in_exports}")

if not proxmox_in_exports:
    print("\n⚠️  Export change didn't persist. QNAP may regenerate /etc/exports from its own DB.")
    print("Checking if QNAP has a different config source...")
    out2, _ = qnap("find /etc/config /usr/local/etc -name '*nfs*' -o -name '*share*' 2>/dev/null | head -10")
    print("NFS config files:", out2)
    out3, _ = qnap("ls /etc/config/ 2>/dev/null | head -20")
    print("/etc/config:", out3)
    # Check if there's a QNAP NFS config DB
    out4, _ = qnap("cat /etc/config/nfs.conf 2>/dev/null || cat /etc/config/smb.conf 2>/dev/null | head -10")
    print("nfs.conf:", out4[:200])

nas.close()

# ── Try remounting on Proxmox with explicit rw option ─────────────────────────
print("\n=== Proxmox: try remounting with explicit rw ===")
prox = paramiko.SSHClient()
prox.set_missing_host_key_policy(paramiko.AutoAddPolicy())
prox.connect(home_env["PROXMOX_HOST"], username="root", password=home_env["PROXMOX_PASSWORD"])

def host(cmd):
    _, out, err = prox.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

def pct(vmid, cmd):
    _, out, err = prox.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# Try umount and remount
host("umount /mnt/pve/qnap-nfs-Multimedia 2>/dev/null; sleep 2")
# Mount explicitly with rw
out5, err5 = host(f"mount -t nfs4 {os.environ['NAS_HOST']}:/Multimedia /mnt/pve/qnap-nfs-Multimedia -o rw,vers=4.1 2>&1")
print(f"Remount: {out5 or err5 or 'ok'}")
time.sleep(2)

out6, err6 = host("touch /mnt/pve/qnap-nfs-Multimedia/Videos/movies/.pve_test 2>&1 && rm -f /mnt/pve/qnap-nfs-Multimedia/Videos/movies/.pve_test && echo WRITABLE || echo READ-ONLY")
print(f"Host write test: {out6 or err6}")

if "WRITABLE" not in (out6 or ""):
    print("\nNFS export still read-only for Proxmox host IP.")
    print(f"The QNAP export is server-controlled — need to add {os.environ['PROXMOX_HOST']} in QNAP NFS UI.")
    print("\n=== Manual fix needed (30 seconds in QNAP UI) ===")
    print(f"1. Open http://{os.environ['NAS_HOST']} → Control Panel → Privilege → Shared Folders")
    print("2. Click 'Multimedia' → Edit → NFS Host Access")  
    print(f"3. Add host: {os.environ['PROXMOX_HOST']}  Access: Read/Write  Root Squash: No")
    print("4. Click OK and Apply")
    print("\nAlternatively via QNAP Web API (no UI needed)...")
    # Try QNAP web API
    import requests as req
    # QNAP HTTP API login
    import urllib3; urllib3.disable_warnings()
    s = req.Session()
    r = s.get(f"http://{os.environ['NAS_HOST']}/cgi-bin/authLogin.cgi",
              params={"user": nas_env["QNAP_SSH_USERNAME"],
                      "pwd": nas_env["QNAP_SSH_PASSWORD"].encode().hex(),
                      "serviceKey": 1}, verify=False, timeout=10)
    print(f"\nQNAP Web API login: {r.status_code}")
    # Check if login returned auth SID
    if "authSid" in r.text or "QTS" in r.text:
        import re
        m = re.search(r'<authSid[^>]*>([^<]+)</authSid>', r.text)
        if m:
            sid = m.group(1)
            print(f"Auth SID: {sid}")
            # Get NFS share info
            r2 = s.get(f"http://{os.environ['NAS_HOST']}/cgi-bin/filemanager/utilRequest.cgi",
                       params={"func": "get_share_info", "sharename": "Multimedia",
                               "sid": sid}, timeout=10)
            print(f"Share info: {r2.text[:300]}")
    else:
        print("QNAP API response:", r.text[:200])
else:
    print("✅ NFS is now writable from Proxmox!")
    # Restart LXCs and set root folders
    for vmid, name in [("107","radarr"), ("111","sonarr"), ("109","qbt")]:
        host(f"pct stop {vmid} 2>/dev/null; sleep 2; pct start {vmid} 2>/dev/null")
    time.sleep(12)

    def add_root_folder(ip, port, api_ver, key, path, name):
        r = requests.get(f"http://{ip}:{port}/api/{api_ver}/rootfolder",
                         headers={"X-Api-Key": key}, timeout=10)
        if any(x["path"] == path for x in r.json()):
            print(f"  {name}: already set ✅"); return
        r2 = requests.post(f"http://{ip}:{port}/api/{api_ver}/rootfolder",
                           headers={"X-Api-Key": key, "Content-Type": "application/json"},
                           data=json.dumps({"path": path}), timeout=10)
        print(f"  {name}: {r2.status_code} {'✅' if r2.status_code in (200,201) else r2.text[:150]}")

    add_root_folder(RADARR_IP, 7878, "v3", RADARR_KEY, "/data/movies",     "Radarr")
    add_root_folder(SONARR_IP, 8989, "v3", SONARR_KEY, "/data/television", "Sonarr")

prox.close()
