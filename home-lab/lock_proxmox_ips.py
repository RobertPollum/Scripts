#!/usr/bin/env python3
"""
Lock static IPs in Proxmox container configs via pct set.
This sets ip= in the net0 config so Proxmox assigns fixed IPs at the veth level.
Also starts CT105 briefly to write its /etc/network/interfaces.
"""
import paramiko
import time
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

HOSTS = [
    (os.environ["PROXMOX_HOST"],  os.environ["PROXMOX_PASSWORD"], [
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
        (105, "jellyfin",     os.environ["JELLYFIN_IP"]),
    ]),
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
    sftp = client.open_sftp()
    with sftp.file(remote_path, "w") as f:
        f.write(content)
    sftp.close()


def get_net0(client, vmid):
    """Get current net0 config string."""
    out, _ = run(client, f"pct config {vmid} | grep '^net0:'")
    return out.replace("net0: ", "").strip()


def set_static_in_pct(client, vmid, ip):
    """Update the pct net0 config to use static IP instead of dhcp."""
    net0 = get_net0(client, vmid)
    if not net0:
        print(f"  WARN: Could not read net0 for CT{vmid}")
        return False

    # Replace ip=dhcp with ip=<static>/24
    if "ip=dhcp" in net0:
        new_net0 = net0.replace("ip=dhcp", f"ip={ip}/24,gw={os.environ['GATEWAY_IP']}")
    elif f"ip={ip}" in net0:
        print(f"  Already has static IP in pct config")
        return True
    else:
        new_net0 = net0 + f",ip={ip}/24,gw={os.environ['GATEWAY_IP']}"

    out, err = run(client, f"pct set {vmid} --net0 '{new_net0}'")
    real_err = [e for e in err.splitlines() if "deprecated" not in e.lower()]
    if real_err:
        print(f"  ERROR: {real_err}")
        return False
    print(f"  pct config locked: ip={ip}/24")
    return True


def push_interfaces(client, vmid, ip):
    """Write static /etc/network/interfaces into a running container."""
    content = IFACE_TEMPLATE.format(ip=ip)
    tmp = f"/tmp/ifaces_{vmid}"
    write_file_via_sftp(client, tmp, content)
    out, err = run(client, f"pct push {vmid} {tmp} /etc/network/interfaces")
    real_err = [e for e in err.splitlines() if "deprecated" not in e.lower()]
    if real_err:
        print(f"  WARN push: {real_err}")
    run(client, f"rm -f {tmp}")
    # Verify
    out, _ = run(client, f"pct exec {vmid} -- cat /etc/network/interfaces")
    return ip in out


def process_host(host, password, containers):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username="root", password=password, timeout=15)
    print(f"\nConnected to {host}")

    for vmid, name, ip in containers:
        print(f"\nCT{vmid} ({name}) -> {ip}")

        # Check if container is running
        out, _ = run(client, f"pct status {vmid}")
        is_running = "running" in out

        # Step 1: Lock IP in pct config (works whether running or stopped)
        set_static_in_pct(client, vmid, ip)

        # Step 2: Write /etc/network/interfaces (running containers only)
        if is_running:
            ok = push_interfaces(client, vmid, ip)
            if ok:
                print(f"  /etc/network/interfaces verified OK")
            else:
                print(f"  WARN: interfaces file verification failed")
        else:
            print(f"  CT{vmid} is stopped - pct config locked, interfaces will be set on next start")

    # Final summary
    print(f"\n--- Current IPs on {host} ---")
    for vmid, name, ip in containers:
        out, _ = run(client, f"pct status {vmid}")
        if "running" in out:
            ipout, _ = run(client, f"pct exec {vmid} -- ip addr show eth0 2>/dev/null | grep 'inet '")
            print(f"  CT{vmid} ({name}): {ipout.strip() or 'no inet addr'}")
        else:
            print(f"  CT{vmid} ({name}): stopped")

    client.close()


def main():
    for host, password, containers in HOSTS:
        process_host(host, password, containers)
    print("\nAll done.")
    print("Next step: Power cycle the Google Wifi primary puck to flush ~150 stale DHCP leases.")


if __name__ == "__main__":
    main()
