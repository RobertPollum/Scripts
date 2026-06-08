"""Probe: get exact qBT schema fields and find Bazarr API key."""
import paramiko, os, requests, json
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def run(vmid, cmd):
    _, out, _ = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip()

# --- Bazarr: find config ---
print("=== Bazarr config search ===")
print(run("112", "find /var/lib/bazarr -type f 2>/dev/null"))
print("---")
print(run("112", "find /opt/bazarr -name 'config.ini' 2>/dev/null"))
print("---")
print(run("112", "ls /var/lib/bazarr/"))

c.close()

# --- qBT schema via Radarr ---
print("\n=== Radarr qBT full schema ===")
key = os.environ["RADARR_API_KEY"]
_env_radarr_ip = os.environ["RADARR_IP"]
r = requests.get(f"http://{_env_radarr_ip}:7878/api/v3/downloadclient/schema", headers={"X-Api-Key": key})
schemas = r.json()
qbt = next((s for s in schemas if s.get("implementation") == "QBittorrent"), None)
if qbt:
    # Print a compact version to POST directly
    template = {k: v for k, v in qbt.items() if k != "id"}
    # Set the fields we want
    for f in template["fields"]:
        if f["name"] == "host":        f["value"] = os.environ["QBITTORRENT_IP"]
        if f["name"] == "port":        f["value"] = 8080
        if f["name"] == "movieCategory": f["value"] = "radarr"
    template["name"] = "qBittorrent"
    template["enable"] = True
    template["priority"] = 1
    template["removeCompletedDownloads"] = True
    template["removeFailedDownloads"] = True
    print("Fields available:", [f["name"] for f in template["fields"]])
    # Try posting it
    r2 = requests.post(f"http://{_env_radarr_ip}:7878/api/v3/downloadclient",
                       headers={"X-Api-Key": key, "Content-Type": "application/json"},
                       data=json.dumps(template))
    print(f"POST status: {r2.status_code}")
    if r2.status_code != 201:
        print("Response:", r2.text[:500])
