"""
Migrate CT105 (Jellyfin) from pve-hp-1 (PROXMOX_HOST) to pve-hp-2 (PROXMOX_HOST2).

Steps:
1. Read CT105 config — capture bind mounts + GPU passthrough dev entries
2. Verify NFS storage and bind mount paths exist on destination
3. Strip bind mounts AND dev passthrough entries from CT105 config (migration rejects both)
4. Offline migrate CT105 to destination node (copies local-lvm disk)
5. Re-add bind mounts + dev entries to CT105 config on destination
6. Start CT105 on destination node

Usage:
  python jellyfin_migrate.py           # full migration
  python jellyfin_migrate.py --dry-run  # inspect only, no changes
"""

import paramiko
import time
import re
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

SRC_HOST = os.environ["PROXMOX_HOST"]
DST_HOST = os.environ["PROXMOX_HOST2"]
USER = "root"
PASSWORD = os.environ["PROXMOX_PASSWORD"]
CTID = 105

DRY_RUN = "--dry-run" in sys.argv


def ssh_connect(host):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=USER, password=PASSWORD, timeout=10)
    return client


def run(client, cmd, check=True):
    print(f"  $ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=60)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        print(f"  {out}")
    if err:
        print(f"  ERR: {err}")
    rc = stdout.channel.recv_exit_status()
    if check and rc != 0:
        raise RuntimeError(f"Command failed (rc={rc}): {cmd}")
    return out, err, rc


def get_ct_config(client):
    """Read CT conf and return raw text, bind mounts, and dev passthrough entries."""
    out, _, _ = run(client, f"cat /etc/pve/lxc/{CTID}.conf")
    lines = out.splitlines()
    bind_mounts = []
    dev_entries = []
    for line in lines:
        # Bind mounts: mp0/mp1 with host path (no ,size= = bind mount)
        if re.match(r'^mp\d+:', line):
            if not re.search(r',size=\d+', line) and ':vm-' not in line and ':subvol-' not in line:
                bind_mounts.append(line)
        # GPU/device passthrough: dev0, dev1, etc.
        elif re.match(r'^dev\d+:', line):
            dev_entries.append(line)
    return out, bind_mounts, dev_entries


def verify_nfs_on_dst(dst_client, bind_mounts):
    """Verify NFS bind mount source paths exist on the destination node."""
    print("\n[2] Verifying bind mount paths on destination...")
    all_ok = True
    for line in bind_mounts:
        m = re.match(r'^mp\d+:\s*([^,]+),', line)
        if m:
            host_path = m.group(1).strip()
            out, _, rc = run(dst_client, f"test -d '{host_path}' && echo EXISTS || echo MISSING", check=False)
            status = "✓" if "EXISTS" in out else "✗ MISSING"
            print(f"  {status}: {host_path}")
            if "MISSING" in out:
                all_ok = False
    if not all_ok:
        raise RuntimeError("One or more bind mount paths are missing on destination. Cannot migrate.")
    print("  All bind mount paths verified.")


def verify_gpu_on_dst(dst_client, dev_entries):
    """Check that GPU device nodes exist on the destination node."""
    print("\n[2b] Verifying GPU/device passthrough paths on destination...")
    warnings = []
    for line in dev_entries:
        # dev0: /dev/dri/renderD128,gid=993  -> extract device path
        m = re.match(r'^dev\d+:\s*([^,]+)', line)
        if m:
            dev_path = m.group(1).strip()
            out, _, rc = run(dst_client, f"test -e '{dev_path}' && echo EXISTS || echo MISSING", check=False)
            status = "✓" if "EXISTS" in out else "✗ MISSING"
            print(f"  {status}: {dev_path}")
            if "MISSING" in out:
                warnings.append(dev_path)
    if warnings:
        print(f"  WARNING: {len(warnings)} device(s) missing on dst. CT will start but GPU passthrough won't work until devices are present.")
        print("  Missing:", warnings)
    else:
        print("  All device paths verified — GPU passthrough should work.")


def strip_entries(src_client, bind_mounts, dev_entries):
    """Comment out bind mounts and dev passthrough entries so migration can proceed."""
    entries_to_strip = bind_mounts + dev_entries
    if not entries_to_strip:
        print("  Nothing to strip.")
        return

    print(f"\n[3] Stripping {len(bind_mounts)} bind mount(s) + {len(dev_entries)} dev entry(s) from CT{CTID} config...")
    if DRY_RUN:
        for e in entries_to_strip:
            print(f"  [DRY-RUN] Would comment out: {e}")
        return

    for entry in entries_to_strip:
        key = entry.split(":")[0]
        run(src_client, f"sed -i 's|^{key}:|#{key}:|' /etc/pve/lxc/{CTID}.conf")
        print(f"  Commented out: {entry}")

    out, _, _ = run(src_client, f"grep -E '^(mp|dev)' /etc/pve/lxc/{CTID}.conf", check=False)
    remaining = out.strip()
    if remaining:
        print(f"  WARNING: These entries were NOT stripped:\n  {remaining}")
    else:
        print("  All bind mounts and dev entries removed from config.")


def restore_entries(dst_client, bind_mounts, dev_entries):
    """Re-add bind mounts and dev entries to CT config on destination node."""
    all_entries = bind_mounts + dev_entries
    if not all_entries:
        print("  Nothing to restore.")
        return

    print(f"\n[5] Restoring {len(bind_mounts)} bind mount(s) + {len(dev_entries)} dev entry(s) on destination CT{CTID}...")
    if DRY_RUN:
        for e in all_entries:
            print(f"  [DRY-RUN] Would restore: {e}")
        return

    for entry in all_entries:
        key = entry.split(":")[0]
        check_out, _, _ = run(dst_client, f"grep -n '^#{key}:' /etc/pve/lxc/{CTID}.conf", check=False)
        if check_out.strip():
            run(dst_client, f"sed -i 's|^#{key}:|{key}:|' /etc/pve/lxc/{CTID}.conf")
            print(f"  Uncommented: {entry}")
        else:
            check_out2, _, _ = run(dst_client, f"grep -n '^{key}:' /etc/pve/lxc/{CTID}.conf", check=False)
            if check_out2.strip():
                print(f"  Already present: {entry}")
            else:
                run(dst_client, f"echo '{entry}' >> /etc/pve/lxc/{CTID}.conf")
                print(f"  Appended: {entry}")

    out, _, _ = run(dst_client, f"cat /etc/pve/lxc/{CTID}.conf")
    print(f"  Final config on dst:\n{out}")


def migrate_ct(src_client, dst_node_name):
    """Stop CT and offline-migrate to the destination node."""
    print(f"\n[4] Stopping CT{CTID} and migrating to {dst_node_name}...")

    if DRY_RUN:
        print(f"  [DRY-RUN] Would run: pct stop {CTID} && pct migrate {CTID} {dst_node_name} --restart 0")
        return

    # Stop CT if running
    status_out, _, _ = run(src_client, f"pct status {CTID}", check=False)
    if "running" in status_out:
        print(f"  Stopping CT{CTID}...")
        run(src_client, f"pct stop {CTID}")
        time.sleep(8)
    else:
        print(f"  CT{CTID} already stopped.")

    # Offline migrate — 16GB disk over LAN, allow up to 10 min
    print(f"  Running: pct migrate {CTID} {dst_node_name} --restart 0")
    print("  (This copies the rootfs disk — may take several minutes...)")
    transport = src_client.get_transport()
    channel = transport.open_session()
    channel.settimeout(600)
    channel.exec_command(f"pct migrate {CTID} {dst_node_name} --restart 0")
    while True:
        if channel.recv_ready():
            data = channel.recv(4096).decode(errors="replace")
            for line in data.splitlines():
                print(f"  {line}")
        if channel.recv_stderr_ready():
            err = channel.recv_stderr(4096).decode(errors="replace")
            for line in err.splitlines():
                print(f"  ERR: {line}")
        if channel.exit_status_ready():
            break
        time.sleep(1)
    rc = channel.recv_exit_status()
    if rc != 0:
        raise RuntimeError(f"Migration failed (rc={rc})")
    print("  Migration complete.")


def get_dst_node_name(dst_client):
    """Get the Proxmox node name of the destination host."""
    out, _, _ = run(dst_client, "hostname")
    return out.strip()


def main():
    print("=" * 60)
    print(f"Jellyfin CT{CTID} Migration: {SRC_HOST} → {DST_HOST}")
    if DRY_RUN:
        print("  *** DRY-RUN MODE — no changes will be made ***")
    print("=" * 60)

    print("\nConnecting to source and destination nodes...")
    src = ssh_connect(SRC_HOST)
    dst = ssh_connect(DST_HOST)

    dst_node_name = get_dst_node_name(dst)
    print(f"Destination node name: {dst_node_name}")

    # Step 1: Read CT105 config
    print(f"\n[1] Reading CT{CTID} config on source...")
    raw_config, bind_mounts, dev_entries = get_ct_config(src)
    print(f"\n  Bind mounts ({len(bind_mounts)}):")
    for bm in bind_mounts:
        print(f"    {bm}")
    print(f"  Dev passthrough ({len(dev_entries)}):")
    for de in dev_entries:
        print(f"    {de}")

    # Step 2: Verify paths on dst
    if bind_mounts:
        verify_nfs_on_dst(dst, bind_mounts)
    if dev_entries:
        verify_gpu_on_dst(dst, dev_entries)

    # Step 3: Strip bind mounts + dev entries from src config
    strip_entries(src, bind_mounts, dev_entries)

    # Step 4: Migrate
    migrate_ct(src, dst_node_name)

    # Step 5: Restore bind mounts + dev entries on dst
    restore_entries(dst, bind_mounts, dev_entries)

    # Step 6: Start CT on dst
    if not DRY_RUN:
        print(f"\n[6] Starting CT{CTID} on destination node...")
        run(dst, f"pct start {CTID}")
        time.sleep(8)
        status_out, _, _ = run(dst, f"pct status {CTID}")
        print(f"  CT{CTID} status: {status_out}")
    else:
        print(f"\n[6] [DRY-RUN] Would start CT{CTID} on {dst_node_name}")

    src.close()
    dst.close()

    if DRY_RUN:
        print("\nDry run complete. Run without --dry-run to execute migration.")
    else:
        print("\nDone! Jellyfin should now be running on the new node.")
        print(f"Access at: http://{os.environ['JELLYFIN_IP']}:8096")
        print(f"Proxmox UI: https://{DST_HOST}:8006")


if __name__ == "__main__":
    main()
