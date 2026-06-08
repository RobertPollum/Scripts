"""
Diagnose KVM availability on Proxmox host and find HAOS VM config.
"""
import paramiko
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

HOST = os.environ["PROXMOX_HOST"]
USER = os.environ["PROXMOX_USER"].split("@")[0]
PASS = os.environ["PROXMOX_PASSWORD"]


def get_client():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=10)
    return c


def run(client, cmd, label=None):
    _, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    print(f"\n$ {label or cmd}")
    if out:
        print(out, end="")
    if err:
        print("[err]", err, end="")
    return out, err


client = get_client()
print(f"=== KVM / HAOS Diagnostics on {HOST} ===\n")

# KVM modules loaded?
run(client, "lsmod | grep kvm", "KVM modules (lsmod)")

# CPU virtualization flags exposed?
run(client, "grep -o -E '(vmx|svm)' /proc/cpuinfo | sort -u", "CPU virt flags (vmx=Intel, svm=AMD)")

# /dev/kvm present?
run(client, "ls -la /dev/kvm 2>/dev/null || echo 'NO /dev/kvm'", "/dev/kvm device")

# List all VMs
run(client, "qm list", "All VMs")

# Find HAOS VM config
run(client, "grep -rl 'home.assistant\\|haos\\|homeassistant' /etc/pve/qemu-server/ 2>/dev/null", "HAOS VM config search")

# Show all VM configs with their IDs
run(client, "ls /etc/pve/qemu-server/", "All VM config files")

client.close()
print("\n=== Done ===")
