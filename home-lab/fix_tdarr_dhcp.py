#!/usr/bin/env python3
"""Fix CT108 (tdarr) runaway dhclient that has accumulated ~150 IPs."""
import paramiko
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

HOST = os.environ["PROXMOX_HOST"]
PASSWORD = os.environ["PROXMOX_PASSWORD"]
CT = "108"

FIX_SCRIPT = (
    "pkill -f 'dhclient.*eth0' 2>/dev/null; "
    "sleep 2; "
    "ip addr flush dev eth0; "
    "rm -f /var/lib/dhcp/dhclient.eth0.leases; "
    "dhclient -1 eth0 &"
)


def run(client, cmd, timeout=60):
    print(f"  >> {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out:
        print(out.rstrip())
    if err:
        print("[stderr]", err.rstrip())
    return out


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", password=PASSWORD, timeout=15)
    print(f"[*] Connected to {HOST}")

    print("[*] Checking current IP count on CT108...")
    run(client, f"pct exec {CT} -- ip addr show eth0 | grep -c 'inet '")

    print("[*] Writing fix script to Proxmox host...")
    run(client, f"cat > /tmp/ct_fix.sh << 'ENDOFSCRIPT'\n{FIX_SCRIPT}\nENDOFSCRIPT")
    run(client, f"chmod +x /tmp/ct_fix.sh")

    print("[*] Pushing script into CT108...")
    run(client, f"pct push {CT} /tmp/ct_fix.sh /tmp/ct_fix.sh")

    print("[*] Running fix inside CT108 (kills dhclient, flushes IPs, starts fresh lease)...")
    run(client, f"pct exec {CT} -- bash /tmp/ct_fix.sh", timeout=30)

    print("[*] Waiting 8s for DHCP lease...")
    import time; time.sleep(8)

    print("[*] Verifying - final IP count on CT108:")
    run(client, f"pct exec {CT} -- ip addr show eth0 | grep 'inet '")

    client.close()
    print("[*] Done.")


if __name__ == "__main__":
    main()
