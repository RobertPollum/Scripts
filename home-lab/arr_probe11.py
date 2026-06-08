"""Reset qBT WebUI password to a known value via config file edit."""
import paramiko, os, requests, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def run(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

NEW_PASS = os.environ["QBITTORRENT_PASSWORD"]

# qBittorrent stores password as PBKDF2. When you delete the password lines,
# it falls back to no-auth on next start (or we can use python to generate hash)
# Easiest: generate PBKDF2 hash using the same algorithm qBT uses
print("=== Generating qBT PBKDF2 hash ===")
# qBT uses PBKDF2-HMAC-SHA512, 100000 iterations, 64 byte key
hash_script = f"""python3 -c "
import hashlib, os, base64
salt = os.urandom(16)
dk = hashlib.pbkdf2_hmac('sha512', '{NEW_PASS}'.encode(), salt, 100000, dklen=64)
salt_b64 = base64.b64encode(salt).decode()
dk_b64 = base64.b64encode(dk).decode()
print(f'@ByteArray({{salt_b64}}:{{dk_b64}})')
" """
out, err = run("109", hash_script)
print("hash:", out)
print("err:", err)

if out.startswith("@ByteArray("):
    print("\n=== Updating qBT config ===")
    # Stop qBT, update config, restart
    run("109", "systemctl stop qbittorrent-nox@root 2>/dev/null || pkill qbittorrent-nox")
    time.sleep(2)

    # Escape for sed
    escaped = out.replace("/", r"\/").replace("&", r"\&").replace("(", r"\(").replace(")", r"\)")
    run("109", f"sed -i 's/WebUI\\\\\\\\Password_PBKDF2=.*/WebUI\\\\\\\\Password_PBKDF2=\"{escaped}\"/' /root/.config/qBittorrent/qBittorrent.conf")
    # Verify
    out2, _ = run("109", "grep Password_PBKDF2 /root/.config/qBittorrent/qBittorrent.conf")
    print("Updated config:", out2[:80])

    run("109", "systemctl start qbittorrent-nox@root 2>/dev/null || qbittorrent-nox --webui-port=8090 &")
    time.sleep(5)

    # Test login
    s = requests.Session()
    _env_qbittorrent_ip = os.environ["QBITTORRENT_IP"]
    r = s.post(f"http://{_env_qbittorrent_ip}:8090/api/v2/auth/login",
               data={"username": "admin", "password": NEW_PASS})
    print(f"\nLogin test: {r.status_code} {r.text!r}")
    if r.text == "Ok.":
        print("✅ qBT password reset successful!")
    else:
        print("❌ Still failing - may need manual reset")

c.close()
