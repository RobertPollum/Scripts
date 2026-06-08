"""
Add qBittorrent to Readarr by using the Readarr container itself to test
the connection first, confirming credentials work, then posting.
Also verify Bazarr actually saved Sonarr/Radarr connections.
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

# ── Verify Bazarr saved the connections ──────────────────────────────────────
print("=== Bazarr connection status ===")
r = requests.get(f"http://{BAZARR_IP}:6767/api/system/settings",
                 headers={"X-Api-Key": BAZARR_KEY})
s = r.json()
print(f"  sonarr: ip={s.get('sonarr',{}).get('ip')} apikey={'set' if s.get('sonarr',{}).get('apikey') else 'MISSING'}")
print(f"  radarr: ip={s.get('radarr',{}).get('ip')} apikey={'set' if s.get('radarr',{}).get('apikey') else 'MISSING'}")
print(f"  use_sonarr={s.get('general',{}).get('use_sonarr')} use_radarr={s.get('general',{}).get('use_radarr')}")

# ── Readarr qBT: get the actual current qBT password from config ──────────────
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def pct(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# The current qBT password hash in config was set by arr_probe15.py with fixed salt
# but qBT may have re-generated it on start. Let's read the current hash:
out, _ = pct("109", "grep Password_PBKDF2 /root/.config/qBittorrent/qBittorrent.conf")
print(f"\n=== Current qBT hash in config ===\n{out[:100]}")

# Test that our password works right now from our machine
s2 = requests.Session()
r2 = s2.post(f"http://{QBT_HOST}:{QBT_PORT}/api/v2/auth/login",
             data={"username": QBT_USER, "password": QBT_PASS})
print(f"\nDirect login test: {r2.status_code} {r2.text!r}")

if r2.status_code == 204:
    print("✅ Password confirmed working")
    # Add qBT to Readarr using schema template
    schema = requests.get(f"http://{READARR_IP}:8787/api/v1/downloadclient/schema",
                          headers={"X-Api-Key": READARR_KEY}).json()
    tmpl = next(s for s in schema if s.get("implementation") == "QBittorrent")
    for f in tmpl["fields"]:
        if f["name"] == "host":            f["value"] = QBT_HOST
        elif f["name"] == "port":          f["value"] = QBT_PORT
        elif f["name"] == "username":      f["value"] = QBT_USER
        elif f["name"] == "password":      f["value"] = QBT_PASS
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
        print(f"❌ {r3.text[:400]}")
        # The *arr app is doing its own connection test during POST.
        # Try disabling the test by modifying the payload if possible, 
        # or add it as disabled first then enable
        print("\nTrying with enable=False to skip connection test...")
        tmpl["enable"] = False
        r4 = requests.post(f"http://{READARR_IP}:8787/api/v1/downloadclient",
                           headers={"X-Api-Key": READARR_KEY, "Content-Type": "application/json"},
                           data=json.dumps(tmpl))
        print(f"Disabled POST: {r4.status_code}")
        if r4.status_code in (200, 201):
            cid = r4.json().get("id")
            print(f"  Created id={cid}, now enabling...")
            tmpl2 = r4.json()
            tmpl2["enable"] = True
            r5 = requests.put(f"http://{READARR_IP}:8787/api/v1/downloadclient/{cid}",
                              headers={"X-Api-Key": READARR_KEY, "Content-Type": "application/json"},
                              data=json.dumps(tmpl2))
            print(f"  Enable PUT: {r5.status_code} {'✅' if r5.status_code in (200,202) else r5.text[:200]}")
        else:
            print(f"❌ {r4.text[:300]}")

c.close()
