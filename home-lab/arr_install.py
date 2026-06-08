"""
Install missing *Arr stack LXCs on Proxmox via community-scripts.
Apps: Prowlarr, Sonarr, Bazarr, Readarr

Each script is downloaded to /tmp on the Proxmox host and run with a PTY
so interactive prompts (including 'clear') work correctly.
Just press Enter to accept defaults at each prompt.
"""
import paramiko
import time
import sys
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(Path(__file__).parent / ".env")

HOST = os.environ["PROXMOX_HOST"]
USER = os.environ["PROXMOX_USER"].split("@")[0]
PASS = os.environ["PROXMOX_PASSWORD"]

APPS = [
    {
        "name": "Prowlarr",
        "script": "prowlarr",
        "port": 9696,
        "note": "Indexer manager — configure this first before Radarr/Sonarr/Readarr",
    },
    {
        "name": "Sonarr",
        "script": "sonarr",
        "port": 8989,
        "note": "TV shows & anime",
    },
    {
        "name": "Bazarr",
        "script": "bazarr",
        "port": 6767,
        "note": "Auto subtitle downloads — connect to Sonarr & Radarr after install",
    },
    {
        "name": "Readarr",
        "script": "readarr",
        "port": 8787,
        "note": f"Book/eBook downloader — pairs with Calibre-Web ({os.environ['CALIBRE_IP']})",
    },
]


def get_client():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=10)
    return c


def get_lxc_ids(client):
    """Return set of current LXC VMIDs."""
    _, out, _ = client.exec_command("pct list | awk 'NR>1 {print $1}'")
    return set(out.read().decode().split())


def tail_log(client, log_path, last_size):
    """Print any new content appended to log_path since last_size bytes."""
    _, out, _ = client.exec_command(f"wc -c < {log_path} 2>/dev/null || echo 0")
    cur_size = int(out.read().decode().strip() or 0)
    if cur_size > last_size:
        _, out, _ = client.exec_command(f"tail -c +{last_size + 1} {log_path} 2>/dev/null")
        data = out.read().decode(errors="replace")
        if data:
            print(data, end="", flush=True)
    return cur_size


def install_app(client, app):
    name = app["name"]
    script = app["script"]
    url = f"https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/{script}.sh"
    log_path = f"/tmp/{script}_install.log"

    print(f"\n{'='*60}")
    print(f"  Installing {name} (port {app['port']})")
    print(f"  {app['note']}")
    print(f"{'='*60}")

    # Snapshot current LXC IDs so we can detect when the new one appears
    ids_before = get_lxc_ids(client)

    # Write wrapper via SFTP — no shell escaping issues
    # Uses PHS_SILENT=1 (skips whiptail menus) + overrides clear() as no-op
    wrapper_path = f"/tmp/{script}_wrapper.sh"
    wrapper_content = "\n".join([
        "#!/usr/bin/env bash",
        "export TERM=xterm",
        # mode=default skips the whiptail install menu (see install_script() in build.func)
        "export mode=default",
        # Override clear() as no-op since we still don't have a display TTY
        "clear() { :; }",
        "export -f clear",
        # Bypass the /dev/tty host-upgrade prompt by overriding the function
        # that calls it. The check_pve_version() function shows options 1/2/3;
        # we redefine it to always choose 2 (Ignore) silently.
        "check_pve_version() { return 0; }",
        "export -f check_pve_version",
        f"source /tmp/{script}.sh",
        "",
    ])
    sftp = client.open_sftp()
    print("  > Downloading install script...")
    _, dl_out, dl_err = client.exec_command(f"curl -fsSL {url} -o /tmp/{script}.sh && echo OK")
    if "OK" not in dl_out.read().decode():
        print(f"  [ERROR] Download failed: {dl_err.read().decode()}")
        return False
    with sftp.open(wrapper_path, "w") as f:
        f.write(wrapper_content)
    sftp.chmod(wrapper_path, 0o755)
    sftp.close()

    # Use 'script -q -c' to allocate a real PTY on the Proxmox host so that
    # /dev/tty resolves inside the installer. Pipe '2\n' (Ignore host upgrade)
    # into stdin so any /dev/tty reads that fall through still get an answer.
    # Run detached via nohup so our SSH channel can exit while install continues.
    run_cmd = (
        f"nohup bash -c "
        f"\"printf '2\\n' | script -q -c 'bash {wrapper_path}' /dev/null\" "
        f"> {log_path} 2>&1 &"
    )
    print(f"  > Launching installer in background on Proxmox...")
    print(f"  > Tailing log: {log_path}")
    print(f"  {'─'*56}")
    client.exec_command(run_cmd)

    # Poll: tail the log and watch for the new LXC to appear
    timeout = 600
    start = time.time()
    log_size = 0
    new_vmid = None

    while time.time() - start < timeout:
        time.sleep(5)
        log_size = tail_log(client, log_path, log_size)

        ids_now = get_lxc_ids(client)
        new_ids = ids_now - ids_before
        if new_ids:
            new_vmid = sorted(new_ids)[-1]
            # Wait a bit more for final log output
            time.sleep(10)
            tail_log(client, log_path, log_size)
            print(f"\n  ✅ {name} installed — new LXC VMID: {new_vmid}")
            # Print the assigned IP
            _, ip_out, _ = client.exec_command(f"pct exec {new_vmid} -- hostname -I 2>/dev/null")
            ip = ip_out.read().decode().strip()
            if ip:
                print(f"  IP: {ip}  —  http://{ip}:{app['port']}")
            return True

    # Timed out — dump last lines of log for diagnosis
    print(f"\n  [TIMEOUT] {name} install exceeded {timeout}s")
    _, out, _ = client.exec_command(f"tail -20 {log_path} 2>/dev/null")
    print(out.read().decode())
    return False


def list_lxcs(client):
    _, stdout, _ = client.exec_command("pvesh get /nodes/pve-hp-1/lxc --output-format table 2>/dev/null || pct list")
    print(stdout.read().decode())


def main():
    # Allow installing a single app: python arr_install.py prowlarr
    target = sys.argv[1].lower() if len(sys.argv) > 1 else None
    apps = [a for a in APPS if target is None or a["script"] == target]

    if not apps:
        print(f"Unknown app '{target}'. Choose from: {[a['script'] for a in APPS]}")
        sys.exit(1)

    client = get_client()
    print(f"Connected to Proxmox at {HOST}")
    print(f"\nCurrent LXC containers:")
    list_lxcs(client)

    results = []
    for app in apps:
        ok = install_app(client, app)
        results.append((app["name"], ok))

    client.close()

    print(f"\n{'='*60}")
    print("  INSTALL SUMMARY")
    print(f"{'='*60}")
    for name, ok in results:
        status = "✅ OK" if ok else "❌ FAILED"
        print(f"  {status}  {name}")

    print(f"\n  Next steps after install:")
    print(f"  1. Open Prowlarr and add indexers (e.g. 1337x, RARBG mirrors, Nyaa for anime)")
    print(f"  2. In Prowlarr → Settings → Apps → add Radarr, Sonarr, Readarr")
    print(f"  3. In Radarr/Sonarr/Readarr → Settings → Download Clients → add qBittorrent ({os.environ['QBITTORRENT_IP']}:8080)")
    print(f"  4. In Bazarr → connect to Sonarr (port 8989) and Radarr (port 7878)")
    print(f"  5. In Jellyseerr → connect to Sonarr + Radarr")


if __name__ == "__main__":
    main()
