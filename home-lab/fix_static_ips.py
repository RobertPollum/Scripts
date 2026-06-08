#!/usr/bin/env python3
"""
Set static IPs on all Proxmox LXC containers to prevent DHCP pool exhaustion.
CT108 (tdarr) had a runaway dhclient causing DHCPDECLINE loop -> 150+ IPs consumed.
"""
import paramiko
import io
import time
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

HOST = os.environ["PROXMOX_HOST"]
PASSWORD = os.environ["PROXMOX_PASSWORD"]

CONTAINERS = [
    (102, "ironclaw",     os.environ["IRONCLAW_IP"]),
    (103, "calibre-web",  os.environ["CALIBRE_IP"]),
    (104, "waydroid",     os.environ["WAYDROID_IP"]),
    (106, "seerr",        os.environ["SEERR_IP"]),
    (107, "radarr",       os.environ["RADARR_IP"]),
    (108, "tdarr",        os.environ["TDARR_IP"]),
    (109, "qbittorrent",  os.environ["QBITTORRENT_IP"]),
    (110, "prowlarr",     os.environ["PROWLARR_IP"]),
    (111, "sonarr",       os.environ["SONARR_IP"]),
    (112, "bazarr",       os.environ["BAZARR_IP"]),
    (113, "readarr",      os.environ["READARR_IP"]),
    (114, "flaresolverr", os.environ["FLARESOLVERR_IP"]),
    (115, "tailscale",    os.environ["TAILSCALE_IP"]),
]

IFACE_TEMPLATE = """\
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet static
    address {ip}
    netmask 255.255.255.0
    gateway {os.environ["GATEWAY_IP"]}
    dns-nameservers 8.8.8.8 1.1.1.1
"""


def run(client, cmd, timeout=20):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out, err


def write_file_via_sftp(client, remote_path, content):
    """Write content to a file on the remote host via SFTP."""
    sftp = client.open_sftp()
    with sftp.file(remote_path, "w") as f:
        f.write(content)
    sftp.close()


def set_static_ip(client, vmid, name, ip):
    content = IFACE_TEMPLATE.format(ip=ip)

    # Write the interfaces file to Proxmox host first
    tmp_path = f"/tmp/ifaces_{vmid}"
    write_file_via_sftp(client, tmp_path, content)

    # Push into the container
    out, err = run(client, f"pct push {vmid} {tmp_path} /etc/network/interfaces")
    if err and "error" in err.lower() and "deprecated" not in err.lower():
        print(f"  ERROR pushing: {err}")
        return False

    # Clean up tmp file
    run(client, f"rm -f {tmp_path}")

    # Verify it was written
    out, err = run(client, f"pct exec {vmid} -- cat /etc/network/interfaces")
    if ip in out:
        print(f"  OK - /etc/network/interfaces set to {ip}")
        return True
    else:
        print(f"  WARN - verification failed: {out}")
        return False


def apply_static_now(client, vmid, ip):
    """Apply static IP immediately without full restart (CT108 specific - fix active issue)."""
    # Kill any dhclient, flush, set static
    cmds = [
        "pkill -f dhclient 2>/dev/null; true",
        "sleep 1",
        f"ip addr flush dev eth0",
        f"ip addr add {ip}/24 dev eth0",
        f"ip route add default via {os.environ['GATEWAY_IP']} dev eth0 2>/dev/null; true",
    ]
    for cmd in cmds:
        out, err = run(client, f"pct exec {vmid} -- bash -c '{cmd}'", timeout=15)
    out, err = run(client, f"pct exec {vmid} -- ip addr show eth0 | grep inet")
    print(f"  Live IPs now: {out}")


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", password=PASSWORD, timeout=15)
    print(f"Connected to {HOST}\n")

    for vmid, name, ip in CONTAINERS:
        print(f"CT{vmid} ({name}) -> {ip}")
        ok = set_static_ip(client, vmid, name, ip)

        # For CT108, also apply it live since it currently has a random IP
        if vmid == 108 and ok:
            print(f"  Applying static IP live on CT108...")
            apply_static_now(client, vmid, ip)

    print("\n--- Summary ---")
    print("Checking current IPs on all containers:")
    for vmid, name, ip in CONTAINERS:
        out, _ = run(client, f"pct exec {vmid} -- ip addr show eth0 | grep 'inet '")
        print(f"  CT{vmid} ({name}): {out.strip()}")

    client.close()
    print("\nDone. All containers have static /etc/network/interfaces configs.")
    print("Note: prowlarr (CT110) uses custom DNS - verify its resolv.conf is still correct.")


if __name__ == "__main__":
    main()
