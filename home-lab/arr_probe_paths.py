"""Check NAS mount point on Proxmox, LXC bind mounts, and current app paths."""
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def host(cmd):
    _, out, _ = c.exec_command(cmd)
    return out.read().decode().strip()

def pct(vmid, cmd):
    _, out, _ = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip()

# 1. Where is the NAS mounted on the Proxmox host?
print("=== NAS / NFS mounts on Proxmox host ===")
print(host("mount | grep -i 'nfs\\|qnap\\|nas\\|multimedia'"))
print(host("df -h | grep -i 'nfs\\|qnap\\|nas\\|multimedia'"))

# 2. /etc/fstab entries
print("\n=== /etc/fstab NFS entries ===")
print(host("grep -i 'nfs\\|qnap\\|nas\\|multimedia' /etc/fstab"))

# 3. What path is the share at?
print("\n=== Find multimedia share path ===")
print(host("find /mnt /media /srv /nas -maxdepth 4 -name 'Multimedia' -o -name 'qnap*' 2>/dev/null | head -10"))

# 4. LXC configs — what's currently bind-mounted for Radarr/Sonarr/Readarr?
for vmid, name in [("107", "radarr"), ("111", "sonarr"), ("113", "readarr"), ("109", "qbt")]:
    print(f"\n=== {name} (CT{vmid}) LXC config mounts ===")
    print(host(f"grep -i 'mp\\|mount' /etc/pve/lxc/{vmid}.conf 2>/dev/null"))

# 5. What paths do the *arr apps currently have configured?
radarr_key  = os.environ["RADARR_API_KEY"]
sonarr_key  = os.environ["SONARR_API_KEY"]
readarr_key = os.environ["READARR_API_KEY"]
print("\n=== Radarr root folders ===")
print(pct("107", f"curl -s http://localhost:7878/api/v3/rootfolder -H 'X-Api-Key: {radarr_key}'"))

print("\n=== Sonarr root folders ===")
print(pct("111", f"curl -s http://localhost:8989/api/v3/rootfolder -H 'X-Api-Key: {sonarr_key}'"))

print("\n=== Readarr root folders ===")
print(pct("113", f"curl -s http://localhost:8787/api/v1/rootfolder -H 'X-Api-Key: {readarr_key}'"))

# 6. qBT save paths
print("\n=== qBT download settings ===")
print(pct("109", "grep -i 'savepath\\|Downloads\\|default_save' /root/.config/qBittorrent/qBittorrent.conf 2>/dev/null"))

c.close()
