"""
Inspect CT105 config and NFS setup on both nodes before migration.
Run this first to verify everything looks correct.
"""

import paramiko
import re
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

SRC_HOST = os.environ["PROXMOX_HOST"]
DST_HOST = os.environ["PROXMOX_HOST2"]
USER = "root"
PASSWORD = os.environ["PROXMOX_PASSWORD"]
CTID = 105


def ssh_connect(host):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=USER, password=PASSWORD, timeout=10)
    return client


def run(client, cmd):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    rc = stdout.channel.recv_exit_status()
    return out, err, rc


def inspect_node(client, label):
    print(f"\n{'='*60}")
    print(f"NODE: {label}")
    print(f"{'='*60}")

    out, _, _ = run(client, "hostname")
    print(f"Hostname: {out}")

    out, _, _ = run(client, "pvecm status 2>/dev/null | head -20")
    print(f"\nCluster status:\n{out}")

    out, _, _ = run(client, "pvesm status")
    print(f"\nStorage:\n{out}")

    out, _, _ = run(client, "findmnt -t nfs,nfs4 --output TARGET,SOURCE,OPTIONS --noheadings 2>/dev/null")
    print(f"\nNFS mounts:\n{out if out else '(none)'}")

    out, _, _ = run(client, "ls /mnt/pve/ 2>/dev/null")
    print(f"\n/mnt/pve/ contents: {out if out else '(empty)'}")


def inspect_ct105(client):
    print(f"\n{'='*60}")
    print(f"CT{CTID} CONFIG on source")
    print(f"{'='*60}")

    out, err, rc = run(client, f"cat /etc/pve/lxc/{CTID}.conf")
    if rc != 0:
        print(f"ERROR: {err}")
        return [], []

    print(out)

    lines = out.splitlines()
    bind_mounts = []
    vol_mounts = []
    for line in lines:
        if re.match(r'^mp\d+:', line):
            if re.search(r',size=\d+', line) or ':vm-' in line or ':subvol-' in line:
                vol_mounts.append(line)
            else:
                bind_mounts.append(line)

    print(f"\nBind mounts detected ({len(bind_mounts)}):")
    for bm in bind_mounts:
        print(f"  {bm}")

    print(f"\nVolume mounts detected ({len(vol_mounts)}):")
    for vm in vol_mounts:
        print(f"  {vm}")

    return bind_mounts, vol_mounts


def check_bind_paths_on_dst(dst_client, bind_mounts):
    print(f"\n{'='*60}")
    print("BIND MOUNT PATH AVAILABILITY ON DESTINATION")
    print(f"{'='*60}")
    for bm in bind_mounts:
        m = re.match(r'^mp\d+:\s*([^,]+),', bm)
        if m:
            host_path = m.group(1).strip()
            out, _, rc = run(dst_client, f"test -d '{host_path}' && echo EXISTS || echo MISSING")
            print(f"  {host_path}: {out}")


def main():
    print("Connecting to nodes...")
    src = ssh_connect(SRC_HOST)
    dst = ssh_connect(DST_HOST)

    inspect_node(src, f"SOURCE ({SRC_HOST})")
    inspect_node(dst, f"DESTINATION ({DST_HOST})")

    bind_mounts, vol_mounts = inspect_ct105(src)

    if bind_mounts:
        check_bind_paths_on_dst(dst, bind_mounts)

    # Check CT status
    print(f"\n{'='*60}")
    print("CT105 CURRENT STATUS")
    print(f"{'='*60}")
    out, _, _ = run(src, f"pct status {CTID}")
    print(f"  {out}")

    src.close()
    dst.close()
    print("\nInspection complete.")


if __name__ == "__main__":
    main()
