"""
Read current Jellyfin server config from Overseerr settings.json,
then update it to the new IP if provided.

Usage:
  python overseerr_update_jellyfin.py              # just read/show current config
  python overseerr_update_jellyfin.py <new-ip>     # update to new IP
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
LXC_ID = "106"
SETTINGS_PATH = "/opt/seerr/config/settings.json"

NEW_IP = sys.argv[1] if len(sys.argv) > 1 else None


def get_client():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=10)
    return c


def run(client, cmd):
    _, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    return out, err


def lxc_run(client, inner_cmd):
    return run(client, f"pct exec {LXC_ID} -- bash -c {repr(inner_cmd)}")


client = get_client()

# Read settings.json
print(f"Reading {SETTINGS_PATH} from LXC {LXC_ID}...\n")
out, err = lxc_run(client, f"cat {SETTINGS_PATH}")
if err and not out:
    print(f"Error reading file: {err}")
    client.close()
    sys.exit(1)

settings = json.loads(out)

# Show Jellyfin config
jellyfin = settings.get("jellyfin", {})
print("=== Current Jellyfin config ===")
print(json.dumps(jellyfin, indent=2))

# Also show main server URL if present
if "hostname" in jellyfin:
    print(f"\nCurrent Jellyfin hostname: {jellyfin['hostname']}")
if "externalHostname" in jellyfin:
    print(f"External hostname: {jellyfin['externalHostname']}")

# Show Jellyfin entries nested under mediaServer or similar keys
for key in ["mediaServerSettings", "jellyfinSettings"]:
    if key in settings:
        print(f"\n[{key}]:", json.dumps(settings[key], indent=2))

if not NEW_IP:
    print("\n--- No new IP provided. Run with: python overseerr_update_jellyfin.py <new-ip> to update. ---")
    client.close()
    sys.exit(0)

# --- UPDATE ---
print(f"\n=== Updating Jellyfin hostname to: {NEW_IP} ===")

# Update hostname in jellyfin section
old_hostname = jellyfin.get("ip", "")
jellyfin["ip"] = NEW_IP
settings["jellyfin"] = jellyfin

# Write back using base64 to avoid any quoting issues
import base64
new_json = json.dumps(settings, indent=2)
b64 = base64.b64encode(new_json.encode()).decode()
write_cmd = f"echo {b64} | base64 -d > {SETTINGS_PATH}"
out2, err2 = lxc_run(client, write_cmd)
if err2:
    print(f"[write err] {err2}")
else:
    print(f"Updated: {old_hostname!r} -> {NEW_IP!r}")

# Restart seerr service
print("\nRestarting seerr service...")
out3, err3 = lxc_run(client, "systemctl restart seerr")
if err3:
    print(f"[restart err] {err3}")
else:
    print("Service restarted.")

# Verify
import time
time.sleep(2)
out4, _ = lxc_run(client, "systemctl is-active seerr")
print(f"seerr status: {out4.strip()}")

client.close()
print("\n=== Done ===")
