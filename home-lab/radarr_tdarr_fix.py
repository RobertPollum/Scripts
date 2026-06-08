"""
Find and update Jellyfin IP in Radarr (107) and Tdarr (108) LXC configs.
"""
import paramiko
import json
import os
import base64
import sys
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

HOST = os.environ["PROXMOX_HOST"]
USER = os.environ["PROXMOX_USER"].split("@")[0]
PASS = os.environ["PROXMOX_PASSWORD"]

OLD_IP = os.environ["PROWLARR_IP"]
NEW_IP = os.environ["JELLYFIN_IP"]


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


def lxc(client, lxc_id, inner_cmd):
    return run(client, f"pct exec {lxc_id} -- bash -c {repr(inner_cmd)}")


def find_and_update(client, lxc_id, name):
    print(f"\n{'='*50}")
    print(f"=== {name} (LXC {lxc_id}) ===")
    print(f"{'='*50}")

    # Search config paths only, exclude binary/apt dirs
    search_paths = "/etc /opt /var/lib/radarr /var/lib/tdarr /root /config /home"
    exclude = "--exclude-dir=/var/cache --exclude-dir=/var/lib/apt --exclude-dir=/var/lib/dpkg --exclude-dir=/proc --include='*.json' --include='*.xml' --include='*.conf' --include='*.ini' --include='*.yaml' --include='*.yml'"
    out, _ = lxc(client, lxc_id,
        f"grep -rl {exclude} '{OLD_IP}' {search_paths} 2>/dev/null | head -20")
    files = [f.strip() for f in out.splitlines() if f.strip()]

    if not files:
        print(f"No config files found referencing {OLD_IP}")
        # Broad jellyfin search in same safe paths
        out2, _ = lxc(client, lxc_id,
            f"grep -rl {exclude} 'jellyfin' {search_paths} 2>/dev/null | head -20")
        jfiles = [f.strip() for f in out2.splitlines() if f.strip()]
        if jfiles:
            print(f"Files referencing 'jellyfin': {jfiles}")
            for f in jfiles:
                content, _ = lxc(client, lxc_id, f"cat {repr(f)}")
                print(f"\n--- {f} ---\n{content[:2000]}")
        else:
            print("No jellyfin references found either.")
        return

    print(f"Files referencing {OLD_IP}:")
    for f in files:
        print(f"  {f}")

    for filepath in files:
        print(f"\n--- Updating: {filepath} ---")
        content, err = lxc(client, lxc_id, f"cat {repr(filepath)}")
        if not content and err:
            print(f"  [read err] {err}")
            continue
        try:
            content = content
        except UnicodeDecodeError:
            print(f"  [skip] binary file: {filepath}")
            continue

        # Try JSON update first
        if filepath.endswith(".json"):
            try:
                data = json.loads(content)
                new_json = json.dumps(content.replace(OLD_IP, NEW_IP))  # fallback
                # Do a recursive string replace on the JSON text
                updated = content.replace(OLD_IP, NEW_IP)
                # Validate it's still valid JSON
                json.loads(updated)
                b64 = base64.b64encode(updated.encode()).decode()
                _, werr = lxc(client, lxc_id, f"echo {b64} | base64 -d > {repr(filepath)}")
                if werr:
                    print(f"  [write err] {werr}")
                else:
                    print(f"  Updated {OLD_IP} -> {NEW_IP} in {filepath}")
            except json.JSONDecodeError:
                print(f"  [warn] Not valid JSON, doing raw replace")
                updated = content.replace(OLD_IP, NEW_IP)
                b64 = base64.b64encode(updated.encode()).decode()
                _, werr = lxc(client, lxc_id, f"echo {b64} | base64 -d > {repr(filepath)}")
                if werr:
                    print(f"  [write err] {werr}")
                else:
                    print(f"  Updated {OLD_IP} -> {NEW_IP} in {filepath}")
        else:
            # Raw text replace (XML, ini, etc.)
            updated = content.replace(OLD_IP, NEW_IP)
            b64 = base64.b64encode(updated.encode()).decode()
            _, werr = lxc(client, lxc_id, f"echo {b64} | base64 -d > {repr(filepath)}")
            if werr:
                print(f"  [write err] {werr}")
            else:
                print(f"  Updated {OLD_IP} -> {NEW_IP} in {filepath}")

    # Restart the main service
    out_svc, _ = lxc(client, lxc_id,
        f"systemctl list-units --all | grep -E 'radarr|tdarr|sonarr' | awk '{{print $1}}' | head -3")
    services = [s.strip() for s in out_svc.splitlines() if s.strip()]
    if services:
        for svc in services:
            print(f"\nRestarting {svc}...")
            _, rerr = lxc(client, lxc_id, f"systemctl restart {svc}")
            if rerr:
                print(f"  [restart err] {rerr}")
            else:
                status, _ = lxc(client, lxc_id, f"systemctl is-active {svc}")
                print(f"  {svc}: {status.strip()}")
    else:
        print("\nNo systemd service found to restart — you may need to restart manually.")


client = get_client()
print(f"Connected to Proxmox {HOST}")
print(f"Updating Jellyfin IP: {OLD_IP} -> {NEW_IP}\n")

find_and_update(client, "107", "Radarr")
find_and_update(client, "108", "Tdarr")

client.close()
print("\n=== All done ===")
