"""Debug: test qBT connectivity from *arr containers + Bazarr key raw read."""
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def run(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    o = out.read().decode().strip()
    e = err.read().decode().strip()
    return o, e

# 1. Can Radarr container reach qBT?
print("=== Network reach from Radarr (107) to qBT ===")
o, e = run("107", f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 5 http://{os.environ['QBITTORRENT_IP']}:8090/")
print("HTTP code:", o, e)
o, e = run("107", f"curl -sv --max-time 5 http://{os.environ['QBITTORRENT_IP']}:8090/ 2>&1 | tail -5")
print("curl:", o)

# 2. Check qBT LXC firewall/iptables
print("\n=== qBT LXC (109) iptables ===")
o, _ = run("109", "iptables -L INPUT -n --line-numbers 2>/dev/null | head -20")
print(o)

# 3. Check qBT WebUI bind address
print("\n=== qBT WebUI bind address ===")
o, _ = run("109", "grep -i 'WebUI\\|Address\\|Listen' /root/.config/qBittorrent/qBittorrent.conf")
print(o)

# 4. Can Proxmox host reach qBT?
_, o, _ = c.exec_command(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 5 http://{os.environ['QBITTORRENT_IP']}:8090/")
print("\n=== Proxmox host → qBT HTTP ===", o.read().decode().strip())

# 5. Bazarr: read raw yaml via grep
print("\n=== Bazarr apikey raw ===")
o, _ = run("112", "grep apikey /opt/bazarr/data/config/config.yaml")
print(o)

c.close()
