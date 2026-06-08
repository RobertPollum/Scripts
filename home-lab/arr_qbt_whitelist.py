"""
Add LAN subnet to qBT AuthSubnetWhitelist so all containers on LOCAL_SUBNET
can connect without needing a password. Then re-add Readarr + fix Bazarr.
"""
import paramiko, os, requests, json, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

READARR_IP  = os.environ["READARR_IP"]
READARR_KEY = os.environ["READARR_API_KEY"]
SONARR_IP   = os.environ["SONARR_IP"]
SONARR_KEY  = os.environ["SONARR_API_KEY"]
RADARR_IP   = os.environ["RADARR_IP"]
RADARR_KEY  = os.environ["RADARR_API_KEY"]
BAZARR_IP   = os.environ["BAZARR_IP"]
BAZARR_KEY  = os.environ["BAZARR_API_KEY"]
QBT_HOST    = os.environ["QBITTORRENT_IP"]
QBT_PORT    = 8090
QBT_USER    = "admin"
QBT_PASS    = os.environ["QBITTORRENT_PASSWORD"]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def pct(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# ── Step 1: Write qBT config with subnet whitelist ────────────────────────────
import hashlib, base64

salt = bytes.fromhex("180ed0a9399ad81a9d9f6aeaa394abe8")
dk = hashlib.pbkdf2_hmac("sha512", QBT_PASS.encode(), salt, 100000, dklen=64)
hash_val = f'@ByteArray({base64.b64encode(salt).decode()}:{base64.b64encode(dk).decode()})'

conf = f"""[BitTorrent]
Session\\AddTorrentStopped=false
Session\\Port=42499
Session\\QueueingSystemEnabled=true
Session\\SSL\\Port=38445
Session\\ShareLimitAction=Stop

[LegalNotice]
Accepted=true

[Meta]
MigrationVersion=8

[Network]
Cookies=@Invalid()
PortForwardingEnabled=false
Proxy\\HostnameLookupEnabled=false
Proxy\\Profiles\\BitTorrent=true
Proxy\\Profiles\\Misc=true
Proxy\\Profiles\\RSS=true

[Preferences]
WebUI\\AuthSubnetWhitelistEnabled=true
WebUI\\AuthSubnetWhitelist={os.environ['LOCAL_SUBNET']}
WebUI\\Password_PBKDF2="{hash_val}"
WebUI\\Port=8090
WebUI\\UseUPnP=false
WebUI\\Username=admin
"""

print("=== Updating qBT config with subnet whitelist ===")
pct("109", "systemctl stop qbittorrent-nox")
time.sleep(3)

sftp = c.open_sftp()
with sftp.open("/tmp/qbt_whitelist.ini", "w") as f:
    f.write(conf)
sftp.close()

_, o, e = c.exec_command(
    "pct push 109 /tmp/qbt_whitelist.ini "
    "/root/.config/qBittorrent/qBittorrent.conf --perms 600"
)
print("push:", o.read().decode().strip(), e.read().decode().strip())

pct("109", "systemctl start qbittorrent-nox")
time.sleep(8)

# Verify whitelist is active
out, _ = pct("109", "grep AuthSubnet /root/.config/qBittorrent/qBittorrent.conf")
print("Whitelist config:", out)

c.close()

# ── Step 2: Verify no-auth access works from LAN ─────────────────────────────
print("\n=== Testing no-auth qBT access ===")
r = requests.get(f"http://{QBT_HOST}:{QBT_PORT}/api/v2/app/version", timeout=10)
print(f"No-auth version: {r.status_code} {r.text!r}")

# ── Step 3: Readarr qBT — now with blank creds (whitelist bypass) ─────────────
print("\n=== Adding qBT to Readarr (whitelist mode, no creds) ===")
# Delete existing disabled client first
existing = requests.get(f"http://{READARR_IP}:8787/api/v1/downloadclient",
                        headers={"X-Api-Key": READARR_KEY}).json()
for client in existing:
    if client.get("implementation") == "QBittorrent":
        cid = client["id"]
        rd = requests.delete(f"http://{READARR_IP}:8787/api/v1/downloadclient/{cid}",
                             headers={"X-Api-Key": READARR_KEY})
        print(f"  Deleted existing client id={cid}: {rd.status_code}")

schema = requests.get(f"http://{READARR_IP}:8787/api/v1/downloadclient/schema",
                      headers={"X-Api-Key": READARR_KEY}).json()
tmpl = next(s for s in schema if s.get("implementation") == "QBittorrent")
for f in tmpl["fields"]:
    if f["name"] == "host":            f["value"] = QBT_HOST
    elif f["name"] == "port":          f["value"] = QBT_PORT
    elif f["name"] == "username":      f["value"] = ""   # blank — whitelist bypasses auth
    elif f["name"] == "password":      f["value"] = ""
    elif f["name"] == "musicCategory": f["value"] = "readarr"
tmpl.update({"name": "qBittorrent", "enable": True, "priority": 1,
             "removeCompletedDownloads": True, "removeFailedDownloads": True})
tmpl.pop("id", None)

r3 = requests.post(f"http://{READARR_IP}:8787/api/v1/downloadclient",
                   headers={"X-Api-Key": READARR_KEY, "Content-Type": "application/json"},
                   data=json.dumps(tmpl))
print(f"Readarr POST: {r3.status_code}")
if r3.status_code in (200, 201):
    print("✅ qBittorrent added to Readarr")
else:
    print(f"❌ {r3.text[:300]}")

# ── Step 4: Fix Bazarr — POST the full settings payload correctly ─────────────
print("\n=== Fixing Bazarr Sonarr/Radarr connections ===")

# GET current full settings, patch sonarr/radarr/general, POST back
current = requests.get(f"http://{BAZARR_IP}:6767/api/system/settings",
                       headers={"X-Api-Key": BAZARR_KEY}).json()

current["sonarr"]["ip"]     = SONARR_IP
current["sonarr"]["port"]   = 8989
current["sonarr"]["apikey"] = SONARR_KEY
current["sonarr"]["ssl"]    = False
current["sonarr"]["base_url"] = "/"
current["radarr"]["ip"]     = RADARR_IP
current["radarr"]["port"]   = 7878
current["radarr"]["apikey"] = RADARR_KEY
current["radarr"]["ssl"]    = False
current["radarr"]["base_url"] = "/"
current["general"]["use_sonarr"] = True
current["general"]["use_radarr"] = True

r4 = requests.post(f"http://{BAZARR_IP}:6767/api/system/settings",
                   headers={"X-Api-Key": BAZARR_KEY, "Content-Type": "application/json"},
                   data=json.dumps(current))
print(f"Bazarr POST: {r4.status_code}")
if r4.status_code in (200, 204):
    # Verify
    verify = requests.get(f"http://{BAZARR_IP}:6767/api/system/settings",
                          headers={"X-Api-Key": BAZARR_KEY}).json()
    si = verify.get("sonarr", {})
    ri = verify.get("radarr", {})
    print(f"  Verified sonarr: ip={si.get('ip')} key={'SET' if si.get('apikey') else 'MISSING'}")
    print(f"  Verified radarr: ip={ri.get('ip')} key={'SET' if ri.get('apikey') else 'MISSING'}")
    print(f"  use_sonarr={verify.get('general',{}).get('use_sonarr')} use_radarr={verify.get('general',{}).get('use_radarr')}")
    if si.get("apikey") and ri.get("apikey"):
        print("  ✅ Bazarr fully configured")
    else:
        print(f"  ⚠️  Keys not persisting — configure manually at http://{os.environ['BAZARR_IP']}:6767")
else:
    print(f"❌ {r4.text[:200]}")
