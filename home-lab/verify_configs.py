#!/usr/bin/env python3
"""Verify pct net0 configs and /etc/network/interfaces on all containers."""
import paramiko
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

HOSTS = [
    (os.environ["PROXMOX_HOST"], os.environ["PROXMOX_PASSWORD"], [
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
    ]),
    (os.environ["PROXMOX_HOST2"], os.environ["PROXMOX_PASSWORD"], [
        (105, "jellyfin", os.environ["JELLYFIN_IP"]),
    ]),
]


def run(client, cmd, timeout=15):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out, err


def main():
    print(f"{'CT':<6} {'Name':<15} {'Target IP':<18} {'pct net0':<8} {'interfaces':<12} {'Live IP'}")
    print("-" * 90)

    for host, password, containers in HOSTS:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username="root", password=password, timeout=15)

        for vmid, name, ip in containers:
            # Check pct config
            out, _ = run(client, f"pct config {vmid} | grep '^net0:'")
            pct_ok = f"ip={ip}" in out

            # Check status
            status_out, _ = run(client, f"pct status {vmid}")
            running = "running" in status_out

            if running:
                # Check interfaces file
                iface_out, _ = run(client, f"pct exec {vmid} -- cat /etc/network/interfaces 2>/dev/null")
                iface_ok = ip in iface_out and "static" in iface_out

                # Check live IP
                live_out, _ = run(client, f"pct exec {vmid} -- ip addr show eth0 2>/dev/null | grep 'inet '")
                live_ip = live_out.split()[1] if live_out else "none"
            else:
                iface_ok = "n/a(stopped)"
                live_ip = "stopped"

            pct_str = "OK" if pct_ok else "FAIL"
            iface_str = "OK" if iface_ok is True else (iface_ok if isinstance(iface_ok, str) else "FAIL")
            print(f"CT{vmid:<4} {name:<15} {ip:<18} {pct_str:<8} {iface_str:<12} {live_ip}")

        client.close()


if __name__ == "__main__":
    main()
