"""Debug: qBT 400 error detail + Bazarr yaml key."""
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

# 1. Bazarr key via python in the container
print("=== Bazarr key via python3 ===")
out = run("112", "python3 -c \"import yaml; d=yaml.safe_load(open('/opt/bazarr/data/config/config.yaml')); print(d['auth']['apikey'])\"")
print("key:", out)

c.close()

# 2. qBT 400 detail - use schema POST with verbose error
print("\n=== qBT 400 detail ===")
radarr_key = os.environ["RADARR_API_KEY"]

# Get full schema from Radarr
_env_radarr_ip = os.environ["RADARR_IP"]
r = requests.get(f"http://{_env_radarr_ip}:7878/api/v3/downloadclient/schema",
                 headers={"X-Api-Key": radarr_key})
schemas = r.json()
qbt = next((s for s in schemas if s.get("implementation") == "QBittorrent"), None)

# Fill in just what we need
for f in qbt["fields"]:
    if f["name"] == "host":           f["value"] = os.environ["QBITTORRENT_IP"]
    elif f["name"] == "port":         f["value"] = 8090
    elif f["name"] == "username":     f["value"] = "admin"
    elif f["name"] == "password":     f["value"] = os.environ["QBITTORRENT_PASSWORD"]
    elif f["name"] == "movieCategory": f["value"] = "radarr"

qbt["name"] = "qBittorrent"
qbt["enable"] = True
qbt["priority"] = 1
qbt["removeCompletedDownloads"] = True
qbt["removeFailedDownloads"] = True
# Remove id field if present
qbt.pop("id", None)

r2 = requests.post(f"http://{_env_radarr_ip}:7878/api/v3/downloadclient",
                   headers={"X-Api-Key": radarr_key, "Content-Type": "application/json"},
                   data=json.dumps(qbt))
print(f"Status: {r2.status_code}")
print(f"Response: {r2.text[:600]}")
