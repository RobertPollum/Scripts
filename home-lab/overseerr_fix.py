"""
Find Overseerr LXC, locate its config file, and update the Jellyfin server IP.
"""
import paramiko
import json
import os
import sys
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
    out = stdout.read().decode()
    err = stderr.read().decode()
    print(f"\n$ {label or cmd}")
    if out:
        print(out, end="")
    if err:
        print("[err]", err, end="")
    return out, err


def lxc(client, lxc_id, inner_cmd, label=None):
    return run(client, f"pct exec {lxc_id} -- bash -c {repr(inner_cmd)}", label=label or inner_cmd)


client = get_client()
print(f"=== Connected to Proxmox {HOST} ===\n")

# List all LXCs
out, _ = run(client, "pct list")

# Find the overseerr LXC ID from the list
overseerr_id = None
for line in out.splitlines():
    if "seerr" in line.lower() or "overseerr" in line.lower():
        overseerr_id = line.split()[0]
        print(f"\n>>> Found Overseerr LXC: {overseerr_id} <<<")
        break

if not overseerr_id:
    print("\nCould not auto-detect Overseerr LXC. Listing all LXCs above — check the name and re-run with LXC_ID set manually.")
    client.close()
    sys.exit(1)

# Get the current IP of this LXC
lxc(client, overseerr_id, "hostname -I", label="Overseerr LXC IP")

# Search common config locations for settings.json
print("\n=== Searching for Overseerr settings.json ===")
lxc(client, overseerr_id, "find / -name 'settings.json' 2>/dev/null | grep -i -E 'overseerr|config|app' | head -10")

# Also check common paths directly
for path in ["/app/config/settings.json", "/opt/overseerr/config/settings.json",
             "/config/settings.json", "/var/lib/overseerr/settings.json"]:
    lxc(client, overseerr_id, f"test -f {path} && echo 'FOUND: {path}' || echo 'not at {path}'")

# Check if running as a docker container
lxc(client, overseerr_id, "which docker && docker ps 2>/dev/null | grep -i seerr || echo 'no docker or no seerr container'")

# Check systemd service
lxc(client, overseerr_id, "systemctl list-units --all '*seerr*' 2>&1")

# Get Jellyfin-related entries from any found settings
lxc(client, overseerr_id,
    "find / -name 'settings.json' 2>/dev/null | xargs grep -l 'jellyfin' 2>/dev/null | head -5")

client.close()
print("\n=== Done ===")
