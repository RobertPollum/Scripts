"""Check Docker state on CT110 and install if missing."""
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def lxc(vmid, cmd, timeout=15):
    _, out, _ = ssh.exec_command(f"pct exec {vmid} -- {cmd}", timeout=timeout)
    return out.read().decode(errors="replace").strip()

def host(cmd, timeout=15):
    _, out, _ = ssh.exec_command(cmd, timeout=timeout)
    return out.read().decode(errors="replace").strip()

print("=== Docker on CT110 ===")
print(lxc("110", "docker --version 2>/dev/null || echo NOT_INSTALLED"))
print(lxc("110", "docker ps 2>/dev/null || echo DOCKER_NOT_RUNNING"))

print()
print("=== CT110 OS ===")
print(lxc("110", "cat /etc/os-release | grep -E '^(NAME|VERSION_ID)'"))

print()
print("=== dpkg lock ===")
print(lxc("110", "fuser /var/lib/dpkg/lock-frontend 2>/dev/null && echo LOCKED || echo FREE"))

print()
print("=== CT110 LXC config (nesting/features for Docker) ===")
print(host("cat /etc/pve/lxc/110.conf | grep -E 'features|nesting|keyctl'"))

ssh.close()
