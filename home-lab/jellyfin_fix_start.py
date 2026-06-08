"""
Fix CT105 startup on hp-pve-2: comment out dev1 (card0 missing) and start CT.
"""
import paramiko
import time
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

DST_HOST = os.environ["PROXMOX_HOST2"]
USER = "root"
PASSWORD = os.environ["PROXMOX_PASSWORD"]
CTID = 105


def ssh_connect(host):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=USER, password=PASSWORD, timeout=10)
    return client


def run(client, cmd, check=True):
    print(f"  $ {cmd}")
    _, stdout, stderr = client.exec_command(cmd, timeout=30)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    rc = stdout.channel.recv_exit_status()
    if out:
        print(f"  {out}")
    if err:
        print(f"  ERR: {err}")
    if check and rc != 0:
        raise RuntimeError(f"Command failed (rc={rc}): {cmd}")
    return out, rc


def main():
    dst = ssh_connect(DST_HOST)

    # Show current dev entries
    print("Current dev entries in CT105 config:")
    run(dst, f"grep -E '^(dev|#dev)' /etc/pve/lxc/{CTID}.conf", check=False)

    # Check which /dev/dri devices actually exist on this node
    print("\nDRI devices on hp-pve-2:")
    run(dst, "ls -la /dev/dri/ 2>/dev/null || echo '(no /dev/dri)'", check=False)

    # Comment out dev1 (card0 doesn't exist on this node)
    print("\nCommenting out dev1 (card0 missing on this node)...")
    run(dst, f"sed -i 's|^dev1:|#dev1:|' /etc/pve/lxc/{CTID}.conf")

    # Verify config
    print("\nUpdated dev entries:")
    run(dst, f"grep -E '^(dev|#dev)' /etc/pve/lxc/{CTID}.conf", check=False)

    # Start CT105
    print(f"\nStarting CT{CTID}...")
    run(dst, f"pct start {CTID}")
    time.sleep(10)

    # Check status and get IP
    out, _ = run(dst, f"pct status {CTID}", check=False)
    print(f"\nCT{CTID} status: {out}")

    run(dst, f"pct exec {CTID} -- ip addr show eth0 2>/dev/null | grep 'inet '", check=False)

    dst.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
