"""Check current qBT config hash and unban IPs, then re-set password."""
import paramiko, os, requests, time, hashlib, base64
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def pct(cmd):
    _, out, err = c.exec_command(f"pct exec 109 -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# Check current config
out, _ = pct("grep -i 'Password\\|Banned\\|Block' /root/.config/qBittorrent/qBittorrent.conf")
print("Current auth config:", out)

# Check if there's a banned IPs list
out2, _ = pct("grep -ri 'ban\\|block' /root/.config/qBittorrent/ 2>/dev/null")
print("Ban/block entries:", out2[:300] if out2 else "(none)")

# Generate a new PBKDF2 hash locally for QBITTORRENT_PASSWORD
NEW_PASS = os.environ["QBITTORRENT_PASSWORD"]
salt = bytes.fromhex("180ed0a9399ad81a9d9f6aeaa394abe8")  # fixed salt for reproducibility
dk = hashlib.pbkdf2_hmac("sha512", NEW_PASS.encode(), salt, 100000, dklen=64)
salt_b64 = base64.b64encode(salt).decode()
dk_b64 = base64.b64encode(dk).decode()
hash_val = f'@ByteArray({salt_b64}:{dk_b64})'
print(f"\nNew hash: {hash_val[:70]}...")

# Stop qBT, write new config, restart
print("Stopping qBT...")
pct("systemctl stop qbittorrent-nox")
time.sleep(3)

sftp = c.open_sftp()
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
WebUI\\Password_PBKDF2="{hash_val}"
WebUI\\Port=8090
WebUI\\UseUPnP=false
WebUI\\Username=admin
"""
with sftp.open("/tmp/qbt_conf_fixed.ini", "w") as f:
    f.write(conf)
sftp.close()

_, push_out, push_err = c.exec_command(
    "pct push 109 /tmp/qbt_conf_fixed.ini /root/.config/qBittorrent/qBittorrent.conf --perms 600"
)
print("push:", push_out.read().decode().strip(), push_err.read().decode().strip())

print("Starting qBT...")
pct("systemctl start qbittorrent-nox")
time.sleep(8)

c.close()

# Test
print("\nTesting login with QBITTORRENT_PASSWORD...")
for attempt in range(3):
    s = requests.Session()
    _env_qbittorrent_ip = os.environ["QBITTORRENT_IP"]
    r = s.post(f"http://{_env_qbittorrent_ip}:8090/api/v2/auth/login",
               data={"username": "admin", "password": NEW_PASS}, timeout=10)
    print(f"  Attempt {attempt+1}: {r.status_code} {r.text!r}")
    if r.status_code in (200, 204):
        r2 = s.get(f"http://{_env_qbittorrent_ip}:8090/api/v2/app/version")
        print(f"  Version: {r2.text}")
        break
    time.sleep(3)
