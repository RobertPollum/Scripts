#!/usr/bin/env python3
"""Fix CT105 (jellyfin) on host 2 - set static IP in interfaces file."""
import paramiko
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

HOST2 = os.environ["PROXMOX_HOST2"]
PASSWORD = os.environ["PROXMOX_PASSWORD"]
JELLYFIN_IP = os.environ["JELLYFIN_IP"]

IFACE_CONTENT = f"""\
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet static
    address {JELLYFIN_IP}
    netmask 255.255.255.0
    gateway {os.environ["GATEWAY_IP"]}
    dns-nameservers 8.8.8.8 1.1.1.1
"""


def run(client, cmd, timeout=15):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out, err


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST2, username="root", password=PASSWORD, timeout=15)
    print(f"Connected to {HOST2}")

    # Check current config
    print("\n=== CT105 pct config ===")
    out, err = run(client, "pct config 105")
    print(out)

    # Container is stopped - write directly to rootfs
    print("\n=== Writing static IP to CT105 rootfs ===")
    rootfs_path = "/var/lib/lxc/105/rootfs/etc/network/interfaces"

    # Use SFTP to write file to host2, then copy into rootfs
    sftp = client.open_sftp()
    with sftp.file("/tmp/ifaces_105", "w") as f:
        f.write(IFACE_CONTENT)
    sftp.close()

    # Check if rootfs path exists
    out, err = run(client, f"ls {rootfs_path} 2>/dev/null && echo EXISTS || echo MISSING")
    print(f"Rootfs interfaces: {out}")

    if "EXISTS" in out:
        out, err = run(client, f"cp /tmp/ifaces_105 {rootfs_path}")
        print(f"Copied: {err or 'OK'}")

        # Verify
        out, err = run(client, f"cat {rootfs_path}")
        print(f"Verified:\n{out}")
    else:
        # Try pct push while stopped - may not work but try
        out, err = run(client, "pct push 105 /tmp/ifaces_105 /etc/network/interfaces")
        print(f"pct push result: {out} {err}")

    client.close()
    print(f"\nDone. CT105 will use static {JELLYFIN_IP} when started.")


if __name__ == "__main__":
    main()
