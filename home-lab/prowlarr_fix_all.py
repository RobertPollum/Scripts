"""
Prowlarr fix script:
1. Re-apply DNS fix on CT110 (Prowlarr LXC) via Proxmox pct exec
2. Add FlareSolverr tag to Torrent Downloads (id:5) and Uindex (id:7)
3. Clear all disabled indexer statuses so they retry immediately
"""
import requests
import json
import subprocess
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_USER = 'root'
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]
CT_ID = 110  # Prowlarr

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR_BASE = f"http://{_env_prowlarr_ip}:9696"
PROWLARR_KEY = os.environ["PROWLARR_API_KEY"]
HEADERS = {'X-Api-Key': PROWLARR_KEY, 'Content-Type': 'application/json'}

FLARESOLVERR_TAG_ID = 1  # Tag "1" is the FlareSolverr proxy tag
CF_INDEXER_IDS = [5, 7]  # Torrent Downloads, Uindex

# ── Step 1: Fix DNS on CT110 via SSH to Proxmox ──────────────────────────────

def run_proxmox_cmd(cmd):
    """Run command inside CT110 via pct exec on Proxmox over SSH."""
    import paramiko
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(PROXMOX_HOST, username=PROXMOX_USER, password=PROXMOX_PASS, timeout=10)
    full_cmd = f"pct exec {CT_ID} -- bash -c '{cmd}'"
    print(f"  [SSH] {full_cmd}")
    stdin, stdout, stderr = ssh.exec_command(full_cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    ssh.close()
    return out, err


def fix_dns():
    print("\n=== STEP 1: Fix DNS on CT110 (Prowlarr) ===")

    # Check current resolv.conf
    out, err = run_proxmox_cmd('cat /etc/resolv.conf')
    print(f"  Current /etc/resolv.conf:\n{out}")

    # Check if dhclient.conf exists
    out2, err2 = run_proxmox_cmd('cat /etc/dhcp/dhclient.conf 2>/dev/null || echo NOT_FOUND')
    print(f"  Current dhclient.conf: {out2[:200]}")

    # Write dhclient.conf with supersede DNS
    dhclient_conf = 'supersede domain-name-servers 1.1.1.1, 8.8.8.8;'
    write_cmd = f'echo "{dhclient_conf}" > /etc/dhcp/dhclient.conf'
    out3, err3 = run_proxmox_cmd(write_cmd)
    print(f"  Wrote dhclient.conf: out={out3} err={err3}")

    # Also directly set resolv.conf to ensure immediate effect
    resolv_cmd = (
        'echo "nameserver 1.1.1.1" > /etc/resolv.conf && '
        'echo "nameserver 8.8.8.8" >> /etc/resolv.conf'
    )
    out4, err4 = run_proxmox_cmd(resolv_cmd)
    print(f"  Updated resolv.conf: out={out4} err={err4}")

    # Verify
    out5, err5 = run_proxmox_cmd('cat /etc/resolv.conf')
    print(f"  Verified /etc/resolv.conf:\n{out5}")

    # Test DNS resolution for a known-failing domain
    out6, err6 = run_proxmox_cmd('nslookup 1337x.to 1.1.1.1 2>&1 | head -5')
    print(f"  DNS test (1337x.to):\n{out6}")

    print("  DNS fix applied.")


# ── Step 2: Add FlareSolverr tag to Torrent Downloads + Uindex ───────────────

def add_flaresolverr_tags():
    print("\n=== STEP 2: Add FlareSolverr tag to Torrent Downloads + Uindex ===")

    r = requests.get(f'{PROWLARR_BASE}/api/v1/indexer', headers=HEADERS)
    indexers = r.json()
    id_map = {ix['id']: ix for ix in indexers}

    for ix_id in CF_INDEXER_IDS:
        ix = id_map.get(ix_id)
        if not ix:
            print(f"  Indexer ID {ix_id} not found, skipping.")
            continue

        current_tags = ix.get('tags', [])
        if FLARESOLVERR_TAG_ID in current_tags:
            print(f"  [{ix['name']}] already has FlareSolverr tag, skipping.")
            continue

        new_tags = current_tags + [FLARESOLVERR_TAG_ID]
        ix['tags'] = new_tags

        put_r = requests.put(
            f'{PROWLARR_BASE}/api/v1/indexer/{ix_id}',
            headers=HEADERS,
            json=ix
        )
        if put_r.status_code in (200, 202):
            print(f"  [{ix['name']}] ✅ Added FlareSolverr tag (tags now: {new_tags})")
        else:
            print(f"  [{ix['name']}] ❌ Failed: {put_r.status_code} {put_r.text[:200]}")


# ── Step 3: Clear disabled indexer statuses ──────────────────────────────────

def clear_indexer_statuses():
    print("\n=== STEP 3: Clear disabled indexer statuses ===")

    r = requests.get(f'{PROWLARR_BASE}/api/v1/indexerstatus', headers=HEADERS)
    statuses = r.json()

    if not statuses:
        print("  No disabled indexers found.")
        return

    r_all = requests.get(f'{PROWLARR_BASE}/api/v1/indexer', headers=HEADERS)
    id_map = {ix['id']: ix['name'] for ix in r_all.json()}

    for s in statuses:
        ix_id = s.get('indexerId')
        name = id_map.get(ix_id, 'Unknown')
        del_r = requests.delete(
            f'{PROWLARR_BASE}/api/v1/indexerstatus/{ix_id}',
            headers=HEADERS
        )
        if del_r.status_code in (200, 202, 204):
            print(f"  [{name}] ✅ Status cleared (was disabled till {s.get('disabledTill')})")
        else:
            print(f"  [{name}] ❌ Failed to clear: {del_r.status_code} {del_r.text[:100]}")

    # Verify
    r2 = requests.get(f'{PROWLARR_BASE}/api/v1/indexerstatus', headers=HEADERS)
    remaining = r2.json()
    print(f"\n  Remaining disabled indexers after clear: {len(remaining)}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    try:
        import paramiko
    except ImportError:
        print("paramiko not installed — installing...")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'paramiko', '-q'])
        import paramiko

    fix_dns()
    add_flaresolverr_tags()
    clear_indexer_statuses()

    print("\n=== ALL FIXES APPLIED ===")
    print("Prowlarr will now retry all previously disabled indexers.")
    print("Monitor Prowlarr UI > Indexers for any remaining errors.")
