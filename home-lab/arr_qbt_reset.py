"""
Reset qBittorrent WebUI password by deleting the hash from config.
qBT will accept the default 'adminadmin' after the hash is removed.
Then we re-login and set it to our desired password via the API.
"""
import paramiko, os, requests, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def pct(cmd):
    _, out, err = c.exec_command(f"pct exec 109 -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

NEW_PASS = os.environ["QBITTORRENT_PASSWORD"]

print("=== Resetting qBT WebUI password ===")

# 1. Stop qBittorrent
print("Stopping qbittorrent-nox...")
pct("systemctl stop qbittorrent-nox@root 2>/dev/null || systemctl stop qbittorrent-nox 2>/dev/null || true")
time.sleep(3)

# 2. Remove the password hash lines from config — qBT uses default 'adminadmin' when absent
conf_path = "/root/.config/qBittorrent/qBittorrent.conf"
pct(f"sed -i '/WebUI.Password_PBKDF2/d' {conf_path}")
pct(f"sed -i '/WebUI.Password_Ha1/d' {conf_path}")  # older format too

# Verify removal
out, _ = pct(f"grep -i password {conf_path}")
print("Password lines remaining:", out or "(none — good)")

# 3. Restart qBittorrent
print("Starting qbittorrent-nox...")
pct("systemctl start qbittorrent-nox@root 2>/dev/null || systemctl start qbittorrent-nox 2>/dev/null || true")
time.sleep(5)

c.close()

# 4. Login with default password and change to desired password
print("\nTesting login with default password (adminadmin)...")
s = requests.Session()
_env_qbittorrent_ip = os.environ["QBITTORRENT_IP"]
r = s.post(f"http://{_env_qbittorrent_ip}:8090/api/v2/auth/login",
           data={"username": "admin", "password": "adminadmin"}, timeout=10)
print(f"Login status: {r.status_code} {r.text!r}")

if r.text.strip() == "Ok.":
    print("✅ Logged in with default password")
    # Set the new password
    r2 = s.post(f"http://{_env_qbittorrent_ip}:8090/api/v2/app/setPreferences",
                data={"json": '{"web_ui_password": "' + NEW_PASS + '"}'}, timeout=10)
    print(f"Set password: {r2.status_code} {r2.text!r}")

    # Verify new password works
    s2 = requests.Session()
    r3 = s2.post(f"http://{_env_qbittorrent_ip}:8090/api/v2/auth/login",
                 data={"username": "admin", "password": NEW_PASS}, timeout=10)
    print(f"New password login: {r3.status_code} {r3.text!r}")
    if r3.text.strip() == "Ok.":
        print(f"✅ Password successfully set to: {NEW_PASS}")
    else:
        print("❌ New password not working — check manually")
elif r.status_code == 403:
    print("403 Forbidden — qBT may still have the old hash. Checking...")
else:
    print("❌ Could not login with default — trying with desired password")
    r4 = s.post(f"http://{_env_qbittorrent_ip}:8090/api/v2/auth/login",
                data={"username": "admin", "password": NEW_PASS}, timeout=10)
    print(f"Desired password login: {r4.status_code} {r4.text!r}")
