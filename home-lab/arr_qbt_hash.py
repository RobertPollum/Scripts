"""
Generate a valid qBittorrent PBKDF2 password hash and write it to the config.
qBT format: @ByteArray(base64_salt:base64_dk)
Algorithm: PBKDF2-HMAC-SHA512, 100000 iterations, 64-byte key
"""
import hashlib, os, base64, paramiko, time, requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

NEW_PASS = os.environ["QBITTORRENT_PASSWORD"]

# Generate the hash locally
salt = os.urandom(16)
dk = hashlib.pbkdf2_hmac("sha512", NEW_PASS.encode(), salt, 100000, dklen=64)
salt_b64 = base64.b64encode(salt).decode()
dk_b64 = base64.b64encode(dk).decode()
hash_val = f'@ByteArray({salt_b64}:{dk_b64})'
print(f"Generated hash: {hash_val[:60]}...")

# Connect and write it
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def pct(cmd):
    _, out, err = c.exec_command(f"pct exec 109 -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# Stop qBT
print("Stopping qbittorrent-nox...")
pct("systemctl stop qbittorrent-nox 2>/dev/null; systemctl stop 'qbittorrent-nox@*' 2>/dev/null; pkill -f qbittorrent-nox; true")
time.sleep(3)

# Write config with new hash via SFTP into the container's rootfs
# Proxmox stores LXC rootfs at /var/lib/lxc/<id>/rootfs
conf_content = f"""[BitTorrent]
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

# Write via SFTP to /tmp on Proxmox host, then copy into container via pct exec
sftp = c.open_sftp()
with sftp.open("/tmp/qbt_conf_new.ini", "w") as f:
    f.write(conf_content)
sftp.close()

# Copy from Proxmox /tmp into the container using pct push
_, out, err = c.exec_command(
    "pct push 109 /tmp/qbt_conf_new.ini /root/.config/qBittorrent/qBittorrent.conf --perms 600"
)
push_out = out.read().decode().strip()
push_err = err.read().decode().strip()
print(f"pct push: {push_out} {push_err}")

# Verify
out2, _ = pct("grep Password_PBKDF2 /root/.config/qBittorrent/qBittorrent.conf")
print(f"Config written: {out2[:60]}...")

# Restart
print("Starting qbittorrent-nox...")
pct("systemctl start qbittorrent-nox")
time.sleep(6)

c.close()

# Test login
print("\nTesting login...")
s = requests.Session()
_env_qbittorrent_ip = os.environ["QBITTORRENT_IP"]
r = s.post(f"http://{_env_qbittorrent_ip}:8090/api/v2/auth/login",
           data={"username": "admin", "password": NEW_PASS}, timeout=10)
print(f"Login: {r.status_code} {r.text!r}")

if r.text.strip() == "Ok.":
    r2 = s.get(f"http://{_env_qbittorrent_ip}:8090/api/v2/app/version", timeout=10)
    print(f"✅ qBT version: {r2.text}")
else:
    print("❌ Login failed")
