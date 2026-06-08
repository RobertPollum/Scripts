"""Add NAS bind mounts and transcode disk to CT108 (tdarr)."""
import paramiko
import os
import time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

HOST = os.environ["PROXMOX_HOST"]
USER = os.environ["PROXMOX_USER"].split("@")[0]
PASS = os.environ["PROXMOX_PASSWORD"]


def run(client, cmd):
    _, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    return out, err


c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)
print(f"Connected to {HOST}")

# Add 12GB local-lvm disk for transcode cache at /transcode
out, err = run(c, "pct set 108 -mp0 local-lvm:12,mp=/transcode")
print(f"ADD DISK (mp0 /transcode): {out.strip() or 'ok'} {err.strip()}")

# Add movies NAS bind mount
out, err = run(c, "pct set 108 -mp1 /mnt/pve/qnap-nfs-Multimedia/Videos/movies,mp=/data/movies")
print(f"ADD MOVIES (mp1): {out.strip() or 'ok'} {err.strip()}")

# Add television NAS bind mount
out, err = run(c, "pct set 108 -mp2 /mnt/pve/qnap-nfs-Multimedia/Videos/television,mp=/data/television")
print(f"ADD TV (mp2): {out.strip() or 'ok'} {err.strip()}")

# Show resulting config
out, err = run(c, "grep -E 'mp[0-9]|rootfs' /etc/pve/lxc/108.conf")
print(f"\nFinal mounts in 108.conf:\n{out}")

# Start CT108
print("Starting CT108...")
out, err = run(c, "pct start 108")
print(f"START: {out.strip() or 'ok'} {err.strip()}")
time.sleep(6)

out, err = run(c, "pct status 108")
print(f"STATUS: {out.strip()}")

# Verify mounts inside container
out, err = run(c, "pct exec 108 -- df -h /transcode /data/movies /data/television")
print(f"\nMount verification inside CT108:\n{out}")
if err:
    print(f"ERR: {err}")

c.close()
print("Done.")
