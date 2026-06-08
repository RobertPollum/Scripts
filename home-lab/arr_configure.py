"""
Configure the Servarr stack after installation:
1. Fetch API keys from each app's config.xml via pct exec
2. Add qBittorrent as download client in Radarr, Sonarr, Readarr
3. Link Radarr, Sonarr, Readarr to Prowlarr
4. Connect Bazarr to Sonarr and Radarr
5. Add Sonarr + Radarr to Jellyseerr
"""
import paramiko
import requests
import json
import time
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]

# LXC IDs and their service config
APPS = {
    "radarr":   {"vmid": "107", "ip": os.environ["RADARR_IP"],  "port": 7878,  "cfg": "/var/lib/radarr/config.xml"},
    "prowlarr": {"vmid": "110", "ip": os.environ["PROWLARR_IP"],  "port": 9696,  "cfg": "/var/lib/prowlarr/config.xml"},
    "sonarr":   {"vmid": "111", "ip": os.environ["SONARR_IP"], "port": 8989,  "cfg": "/var/lib/sonarr/config.xml"},
    "bazarr":   {"vmid": "112", "ip": os.environ["BAZARR_IP"], "port": 6767,  "cfg": None},
    "readarr":  {"vmid": "113", "ip": os.environ["READARR_IP"], "port": 8787,  "cfg": "/var/lib/readarr/config.xml"},
    "jellyseerr": {"vmid": "106", "ip": os.environ["SEERR_IP"], "port": 5055, "cfg": None},
}

QBT_HOST = os.environ["QBITTORRENT_IP"]
QBT_PORT = 8090
QBT_USER = "admin"
QBT_PASS = os.environ["QBITTORRENT_PASSWORD"]


def ssh_client():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS, timeout=10)
    return c


def pct_exec(client, vmid, cmd):
    _, out, err = client.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()


def get_api_key(client, app_name):
    app = APPS[app_name]
    cfg = app["cfg"]
    if not cfg:
        return None
    out, _ = pct_exec(client, app["vmid"], f"grep -oP '(?<=<ApiKey>)[^<]+' {cfg} 2>/dev/null")
    return out or None


def get_ip(client, app_name):
    app = APPS[app_name]
    if app["ip"]:
        return app["ip"]
    out, _ = pct_exec(client, app["vmid"], "hostname -I")
    ip = out.split()[0] if out.split() else None
    APPS[app_name]["ip"] = ip
    return ip


# API version per app (Prowlarr and Readarr use v1, others use v3)
API_VERSION = {
    "radarr":   "v3",
    "sonarr":   "v3",
    "readarr":  "v1",
    "prowlarr": "v1",
}


def arr_get(ip, port, api_key, path, app_name=None):
    ver = API_VERSION.get(app_name, "v3")
    url = f"http://{ip}:{port}/api/{ver}/{path}"
    r = requests.get(url, headers={"X-Api-Key": api_key}, timeout=10)
    r.raise_for_status()
    return r.json()


def arr_post(ip, port, api_key, path, payload, app_name=None):
    ver = API_VERSION.get(app_name, "v3")
    url = f"http://{ip}:{port}/api/{ver}/{path}"
    r = requests.post(url, headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                      data=json.dumps(payload), timeout=10)
    r.raise_for_status()
    return r.json()


# Category field name differs per app
QBT_CATEGORY_FIELD = {
    "radarr":  "movieCategory",
    "sonarr":  "tvCategory",
    "readarr": "musicCategory",  # Readarr reuses musicCategory field name
}


def add_qbt_download_client(app_name, ip, port, api_key):
    """Add qBittorrent as download client using the app's own schema as base template."""
    existing = arr_get(ip, port, api_key, "downloadclient", app_name)
    if any(c.get("implementation") == "QBittorrent" for c in existing):
        print(f"  [{app_name}] qBittorrent already configured")
        return

    # Fetch the schema from the app itself — ensures all required fields are present
    ver = API_VERSION.get(app_name, "v3")
    schema_r = requests.get(f"http://{ip}:{port}/api/{ver}/downloadclient/schema",
                            headers={"X-Api-Key": api_key}, timeout=10)
    schema_r.raise_for_status()
    template = next((s for s in schema_r.json() if s.get("implementation") == "QBittorrent"), None)
    if not template:
        print(f"  [{app_name}] ❌ QBittorrent not found in schema")
        return

    # Patch the fields we care about
    cat_field = QBT_CATEGORY_FIELD.get(app_name, "movieCategory")
    field_overrides = {
        "host":     QBT_HOST,
        "port":     QBT_PORT,
        "username": QBT_USER,
        "password": QBT_PASS,
        cat_field:  app_name,
    }
    for f in template["fields"]:
        if f["name"] in field_overrides:
            f["value"] = field_overrides[f["name"]]

    template["name"] = "qBittorrent"
    template["enable"] = True
    template["priority"] = 1
    template["removeCompletedDownloads"] = True
    template["removeFailedDownloads"] = True
    template.pop("id", None)

    arr_post(ip, port, api_key, "downloadclient", template, app_name)
    print(f"  [{app_name}] ✅ qBittorrent added as download client")


def link_app_to_prowlarr(app_name, app_ip, app_port, app_api_key, prowlarr_ip, prowlarr_port, prowlarr_key):
    """Register an *arr app in Prowlarr's Applications list (Prowlarr uses /api/v1)."""
    existing = arr_get(prowlarr_ip, prowlarr_port, prowlarr_key, "applications", "prowlarr")
    impl_map = {
        "radarr":  ("Radarr",  "RadarrSettings",  [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060]),
        "sonarr":  ("Sonarr",  "SonarrSettings",  [5000, 5010, 5020, 5030, 5040, 5045, 5050, 5060]),
        "readarr": ("Readarr", "ReadarrSettings", [7000, 7010, 7020, 7030]),
    }
    impl, contract, cats = impl_map.get(app_name, (None, None, None))
    if not impl:
        return

    if any(a.get("implementation") == impl for a in existing):
        print(f"  [prowlarr] {app_name} already linked")
        return

    payload = {
        "syncLevel": "fullSync",
        "name": app_name.capitalize(),
        "fields": [
            {"name": "prowlarrUrl",   "value": f"http://{prowlarr_ip}:{prowlarr_port}"},
            {"name": "baseUrl",       "value": f"http://{app_ip}:{app_port}"},
            {"name": "apiKey",        "value": app_api_key},
            {"name": "syncCategories", "value": cats},
            {"name": "syncRejectBlocklistedTorrentHashesWhileGrabbing", "value": False},
        ],
        "implementationName": impl,
        "implementation": impl,
        "configContract": contract,
        "tags": [],
    }
    arr_post(prowlarr_ip, prowlarr_port, prowlarr_key, "applications", payload, "prowlarr")
    print(f"  [prowlarr] ✅ {app_name} linked to Prowlarr")


def get_bazarr_api_key(client):
    """Read Bazarr's API key from its config.yaml."""
    # config.yaml auth section: '  apikey: <32hex>'
    out, _ = pct_exec(client, "112",
        "awk '/^auth:/{f=1} f && /^  apikey:/{print $2; exit}' "
        "/opt/bazarr/data/config/config.yaml 2>/dev/null"
    )
    key = out.strip()
    # Fallback: grep and strip prefix
    if not key:
        out2, _ = pct_exec(client, "112",
            "grep -m1 'apikey:' /opt/bazarr/data/config/config.yaml 2>/dev/null"
        )
        key = out2.strip().split()[-1] if out2.strip() else None
    return key or None


def configure_bazarr(bazarr_ip, sonarr_ip, sonarr_key, radarr_ip, radarr_key, bazarr_key=None):
    """Set Sonarr and Radarr connection in Bazarr via its REST API."""
    base = f"http://{bazarr_ip}:6767"
    if not bazarr_key:
        print(f"  [bazarr] ⚠️  No API key — configure manually at http://{os.environ['BAZARR_IP']}:6767")
        return
    headers = {"Content-Type": "application/json", "X-Api-Key": bazarr_key}

    # Bazarr /api/system/settings uses flat structure matching its GET response
    payload = {
        "sonarr": {
            "ip": sonarr_ip,
            "port": 8989,
            "apikey": sonarr_key,
            "ssl": False,
            "base_url": "/",
            "full_update": "Daily",
            "only_monitored": False,
        },
        "radarr": {
            "ip": radarr_ip,
            "port": 7878,
            "apikey": radarr_key,
            "ssl": False,
            "base_url": "/",
            "full_update": "Daily",
            "only_monitored": False,
        },
        "general": {
            "use_sonarr": True,
            "use_radarr": True,
        },
    }
    try:
        r = requests.post(f"{base}/api/system/settings",
                          headers=headers, data=json.dumps(payload), timeout=10)
        r.raise_for_status()
        print("  [bazarr] ✅ Sonarr + Radarr connected")
    except Exception as e:
        print(f"  [bazarr] ⚠️  API config failed ({r.status_code if 'r' in dir() else '?'}): {e}")
        print(f"  [bazarr]    Configure manually at http://{os.environ['BAZARR_IP']}:6767 → Settings → Sonarr/Radarr")


def configure_jellyseerr(jellyseerr_ip, radarr_ip, radarr_key, sonarr_ip, sonarr_key):
    """Add Radarr and Sonarr to Jellyseerr if not already present."""
    base = f"http://{jellyseerr_ip}:5055/api/v1"
    # Jellyseerr requires a session cookie from login — skip API config and just print instructions
    print("  [jellyseerr] ℹ️  Jellyseerr requires browser login to add Radarr/Sonarr.")
    print(f"  [jellyseerr]    Open http://{jellyseerr_ip}:5055 → Settings → Radarr / Sonarr")
    print(f"  [jellyseerr]    Radarr: {radarr_ip}:7878  key: {radarr_key}")
    print(f"  [jellyseerr]    Sonarr: {sonarr_ip}:8989  key: {sonarr_key}")


def main():
    print("=== Servarr Stack Auto-Configuration ===\n")

    print("Fetching API keys from LXC config files...")
    client = ssh_client()

    keys = {}
    for name in ("radarr", "prowlarr", "sonarr", "readarr"):
        ip = get_ip(client, name)
        key = get_api_key(client, name)
        keys[name] = key
        APPS[name]["ip"] = ip
        print(f"  {name}: IP={ip}  key={key}")

    keys["bazarr"] = get_bazarr_api_key(client)
    print(f"  bazarr: key={keys['bazarr']}")

    client.close()

    readarr_ip = APPS["readarr"]["ip"]
    prowlarr_ip = APPS["prowlarr"]["ip"]
    radarr_ip   = APPS["radarr"]["ip"]
    sonarr_ip   = APPS["sonarr"]["ip"]

    core_apps = ["radarr", "prowlarr", "sonarr", "readarr"]
    if not all(keys[k] for k in core_apps):
        missing = [k for k in core_apps if not keys[k]]
        print(f"\n⚠️  Missing API keys for: {missing}")
        print("Services may still be starting. Waiting 20s and retrying...")
        time.sleep(20)
        client = ssh_client()
        for name in missing:
            keys[name] = get_api_key(client, name)
            print(f"  {name}: key={keys[name]}")
        client.close()

    print("\n--- Step 1: Add qBittorrent to Radarr, Sonarr, Readarr ---")
    for name, ip, port in [
        ("radarr",  radarr_ip,  7878),
        ("sonarr",  sonarr_ip,  8989),
        ("readarr", readarr_ip, 8787),
    ]:
        try:
            add_qbt_download_client(name, ip, port, keys[name])
        except Exception as e:
            print(f"  [{name}] ❌ {e}")

    print("\n--- Step 2: Link apps to Prowlarr ---")
    for name, ip, port in [
        ("radarr",  radarr_ip,  7878),
        ("sonarr",  sonarr_ip,  8989),
        ("readarr", readarr_ip, 8787),
    ]:
        try:
            link_app_to_prowlarr(
                name, ip, port, keys[name],
                prowlarr_ip, 9696, keys["prowlarr"]
            )
        except Exception as e:
            print(f"  [prowlarr←{name}] ❌ {e}")

    print("\n--- Step 3: Connect Bazarr to Sonarr + Radarr ---")
    configure_bazarr(os.environ["BAZARR_IP"], sonarr_ip, keys["sonarr"], radarr_ip, keys["radarr"], keys.get("bazarr"))

    print("\n--- Step 4: Jellyseerr ---")
    configure_jellyseerr(os.environ["SEERR_IP"], radarr_ip, keys["radarr"], sonarr_ip, keys["sonarr"])

    print("\n=== Done ===")
    print("\nRemaining manual steps:")
    print("  • Prowlarr: Add torrent indexers (Nyaa for anime, 1337x, etc.)")
    print(f"    → http://{os.environ['PROWLARR_IP']}:9696 → Indexers → Add Indexer")
    print(f"  • Readarr: Set root folder + link to Calibre-Web ({os.environ['CALIBRE_IP']})")
    print("    → http://{}:8787 → Settings → Media Management → Add Root Folder".format(readarr_ip))


if __name__ == "__main__":
    main()
