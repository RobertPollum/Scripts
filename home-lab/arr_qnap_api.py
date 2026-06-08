"""
Use QNAP Web API to permanently add PROXMOX_HOST as rw NFS host
for the Multimedia shared folder.
"""
import requests, re, json
from pathlib import Path
import urllib3
import os
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
urllib3.disable_warnings()

nas_env = {}
for line in (Path(__file__).parent.parent / "nas-ssh" / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        nas_env[k.strip()] = v.strip()

NAS_HOST  = f"http://{nas_env['QNAP_SSH_HOST']}"
NAS_USER  = nas_env["QNAP_SSH_USERNAME"]
NAS_PASS  = nas_env["QNAP_SSH_PASSWORD"]
PROXMOX_IP = os.environ["PROXMOX_HOST"]

s = requests.Session()
s.verify = False

# ── Step 1: Login to QNAP web API ────────────────────────────────────────────
print("=== QNAP Web API Login ===")
# QNAP QTS uses /cgi-bin/authLogin.cgi with hex-encoded password
pwd_hex = NAS_PASS.encode().hex()
r = s.get(f"{NAS_HOST}/cgi-bin/authLogin.cgi",
          params={"user": NAS_USER, "pwd": pwd_hex, "serviceKey": "1"}, timeout=15)
print(f"Login status: {r.status_code}")

# Extract auth SID from XML response
m = re.search(r'<authSid[^>]*>([^<]+)</authSid>', r.text)
if not m:
    # Try JSON response
    try:
        data = r.json()
        sid = data.get("authSid") or data.get("sid") or data.get("data", {}).get("authSid")
    except Exception:
        sid = None
    if not sid:
        print("Login response:", r.text[:400])
        print("❌ Could not extract auth SID")
        exit(1)
else:
    sid = m.group(1)
print(f"Auth SID: {sid}")

# ── Step 2: Get current NFS settings for Multimedia share ────────────────────
print("\n=== Getting Multimedia share NFS config ===")
r2 = s.get(f"{NAS_HOST}/cgi-bin/filemanager/utilRequest.cgi",
           params={"func": "get_share_info", "sharename": "Multimedia", "sid": sid},
           timeout=15)
print(f"Status: {r2.status_code}")
print(r2.text[:600])

# ── Step 3: Try QNAP share NFS host API ──────────────────────────────────────
print("\n=== Trying NFS host add API ===")
# QNAP API for NFS: func=set_nfs_host_access or similar
for func in ["set_nfs_host", "add_nfs_host", "set_share_nfs", "nfs_add_host"]:
    r3 = s.get(f"{NAS_HOST}/cgi-bin/filemanager/utilRequest.cgi",
               params={"func": func, "sid": sid, "sharename": "Multimedia",
                       "nfshost": PROXMOX_IP, "nfsrw": "1", "rootsquash": "0"},
               timeout=10)
    if r3.status_code == 200 and "error" not in r3.text.lower()[:50]:
        print(f"  {func}: {r3.text[:200]}")
        break
    else:
        print(f"  {func}: {r3.status_code} {r3.text[:50]}")

# ── Step 4: Try the share management CGI ─────────────────────────────────────
print("\n=== Trying share management CGI ===")
r4 = s.get(f"{NAS_HOST}/cgi-bin/filemanager/utilRequest.cgi",
           params={"func": "get_samba_setting", "sid": sid}, timeout=10)
print(f"samba setting: {r4.status_code} {r4.text[:200]}")

# Try listing available funcs via a bogus call
r5 = s.get(f"{NAS_HOST}/cgi-bin/filemanager/utilRequest.cgi",
           params={"func": "get_share_list", "sid": sid, "start": 0, "limit": 20},
           timeout=10)
print(f"\nShare list: {r5.status_code}")
print(r5.text[:400])
