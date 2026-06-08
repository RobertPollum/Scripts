"""
Adds TUN/TAP device passthrough to the qbittorrent LXC config on Proxmox,
then restarts the LXC so /dev/net/tun becomes available inside it.
"""
import time
import paramiko
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(Path(__file__).parent / ".env")

HOST = os.environ["PROXMOX_HOST"]
USER = os.environ["PROXMOX_USER"].split("@")[0]  # strip @pve-hp-1 -> root
PASS = os.environ["PROXMOX_PASSWORD"]

QBT_LXC_ID = None  # will be discovered


KEY_PATH = Path.home() / ".ssh" / "id_ed25519"
KEY_PASSPHRASE = os.environ["QBITTORRENT_PASSWORD"]  # same passphrase as NAS key


def get_client():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    # Try key auth first, then password
    try:
        key = paramiko.Ed25519Key.from_private_key_file(str(KEY_PATH), password=KEY_PASSPHRASE)
        c.connect(HOST, username=USER, pkey=key, timeout=10)
        print("[auth] Connected via SSH key")
    except Exception as e:
        print(f"[auth] Key auth failed ({e}), trying password...")
        c.connect(HOST, username=USER, password=PASS, timeout=10)
        print("[auth] Connected via password")
    return c


def run(client, cmd):
    _, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    print(f"\n$ {cmd}")
    if out:
        print(out, end="")
    if err:
        print("[err]", err, end="")
    return out, err


client = get_client()
print(f"=== Connected to Proxmox {HOST} as {USER} ===\n")

lxc_id = "109"  # qbittorrent LXC
lxc_conf = f"/etc/pve/lxc/{lxc_id}.conf"
print(f"Using LXC ID: {lxc_id}, config: {lxc_conf}")
if True:

    # Show current config
    run(client, f"cat {lxc_conf}")

    # Check if TUN entries already exist
    out2, _ = run(client, f"grep -c 'tun' {lxc_conf}")
    already = int(out2.strip()) if out2.strip().isdigit() else 0

    if already > 0:
        print(f"\nTUN entries already present in {lxc_conf} — no changes needed.")
        run(client, f"grep 'tun\\|cgroup' {lxc_conf}")
    else:
        print(f"\nAdding TUN/TAP passthrough to {lxc_conf}...")
        run(client, f"echo 'lxc.cgroup2.devices.allow = c 10:200 rwm' >> {lxc_conf}")
        run(client, f"echo 'lxc.mount.entry = /dev/net/tun dev/net/tun none bind,create=file' >> {lxc_conf}")

        # Verify lines were added
        run(client, f"tail -5 {lxc_conf}")

        # Restart the LXC
        print(f"\nRestarting LXC {lxc_id}...")
        run(client, f"pct restart {lxc_id}")
        time.sleep(8)

        # Verify TUN device inside LXC
        run(client, f"pct exec {lxc_id} -- ls -la /dev/net/tun")

client.close()
print("\n=== Done ===")
