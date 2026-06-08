import paramiko, os, requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def host(cmd, timeout=15):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    return out.read().decode().strip(), err.read().decode().strip()

def pct(vmid, cmd, timeout=15):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}", timeout=timeout)
    return out.read().decode().strip(), err.read().decode().strip()

print("=== CT111 (Sonarr) LXC config ===")
out, _ = host("cat /etc/pve/lxc/111.conf")
print(out)

print("\n=== NFS mount on Proxmox host ===")
out2, _ = host("mount | grep qnap")
print(out2 or "NO QNAP MOUNTS FOUND")

print("\n=== NAS path accessible on host ===")
out3, _ = host("ls /mnt/pve/qnap-nfs-Multimedia/Videos/television 2>/dev/null | head -5 || echo NOT_ACCESSIBLE")
print(out3)

print("\n=== /data/television inside CT111 ===")
out4, _ = pct("111", "ls /data/television 2>/dev/null | head -5 || echo NOT_MOUNTED")
print(f"  ls: {out4}")

out5, _ = pct("111", "stat /data/television 2>&1 | head -4")
print(f"  stat: {out5}")

out6, _ = pct("111", "df -h /data/television 2>&1")
print(f"  df: {out6}")

out7, _ = pct("111", "touch /data/television/.writetest 2>&1 && echo WRITABLE && rm /data/television/.writetest || echo READ_ONLY")
print(f"  write test: {out7}")

print("\n=== Sonarr root folders (API) ===")
_env_sonarr_ip = os.environ["SONARR_IP"]
r = requests.get(f"http://{_env_sonarr_ip}:8989/api/v3/rootFolder",
                 headers={"X-Api-Key": os.environ["SONARR_API_KEY"]}, timeout=10)
print(f"  HTTP {r.status_code}")
for rf in r.json():
    print(f"  id={rf.get('id')} path={rf.get('path')} accessible={rf.get('accessible')} freeSpace={rf.get('freeSpace',0)//1024//1024//1024}GB")

print("\n=== Sonarr system status ===")
r2 = requests.get(f"http://{_env_sonarr_ip}:8989/api/v3/system/status",
                  headers={"X-Api-Key": os.environ["SONARR_API_KEY"]}, timeout=10)
s = r2.json()
print(f"  appData: {s.get('appData')}")
print(f"  startupPath: {s.get('startupPath')}")

c.close()
