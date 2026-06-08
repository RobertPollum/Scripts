"""Check qBT config state and try bypass auth approaches."""
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

# Full config dump
print("=== Full qBT config ===")
out, _ = pct("cat /root/.config/qBittorrent/qBittorrent.conf")
print(out)

print("\n=== qBT service status ===")
out, _ = pct("systemctl status qbittorrent-nox@root 2>/dev/null || systemctl status qbittorrent-nox 2>/dev/null || ps aux | grep qbit")
print(out[:500])

# Try from inside the container (localhost) — qBT default allows bypass from localhost
print("\n=== Login from inside container ===")
out, err = pct("curl -s -c /tmp/qbt_cookies.txt -b /tmp/qbt_cookies.txt -X POST http://127.0.0.1:8090/api/v2/auth/login -d 'username=admin&password=adminadmin'")
print("adminadmin:", out, err)
out, err = pct("curl -s -c /tmp/qbt_cookies.txt -b /tmp/qbt_cookies.txt http://127.0.0.1:8090/api/v2/app/version")
print("version:", out, err)

c.close()
