"""
Check if Readarr's IP is banned in qBT, clear ban, and check Bazarr save issue.
"""
import paramiko, os, requests, json
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def pct(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# 1. Check qBT ban list in data dir
print("=== qBT ban list ===")
out, _ = pct("109", "cat /root/.local/share/qBittorrent/IP_filtering.dat 2>/dev/null | head -20")
print("IP filter:", out or "(empty)")
_readarr_ip = os.environ["READARR_IP"]
out2, _ = pct("109", f"grep -r {_readarr_ip} /root/.config/qBittorrent/ /root/.local/share/qBittorrent/ 2>/dev/null")
print("Readarr IP in configs:", out2 or "(none)")

# 2. Check qBT logs for ban info
print("\n=== qBT recent logs ===")
out3, _ = pct("109", "journalctl -u qbittorrent-nox --no-pager -n 20 2>/dev/null | tail -15")
print(out3)

# 3. Check if WebUI has LocalHostAuth bypass we can set
print("\n=== qBT WebUI bypass options ===")
out4, _ = pct("109", "grep -i 'auth\\|bypass\\|local' /root/.config/qBittorrent/qBittorrent.conf")
print(out4 or "(none)")

# 4. Try qBT's AuthSubnetWhitelist setting - whitelist the LAN
print("\n=== Add LAN to qBT AuthSubnetWhitelist ===")
# Stop qBT, add whitelist, restart
pct("109", "systemctl stop qbittorrent-nox")
import time; time.sleep(3)

_, push_err = c.exec_command(
    f"pct exec 109 -- bash -c \"echo -e '\\nWebUI\\\\\\\\AuthSubnetWhitelistEnabled=true\\nWebUI\\\\\\\\AuthSubnetWhitelist={os.environ['LOCAL_SUBNET']}' "
    ">> /root/.config/qBittorrent/qBittorrent.conf\""
)
# Actually use sed approach instead
sftp = c.open_sftp()
out5, _ = pct("109", "cat /root/.config/qBittorrent/qBittorrent.conf")
print("Current config:")
print(out5)

c.close()
