"""Quick probe: find Bazarr config path and API key."""
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def run(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c '{cmd}'")
    return out.read().decode().strip()

print("=== Bazarr (112) ===")
print("var/lib:", run("112", "ls /var/lib/ 2>/dev/null"))
print("proc:   ", run("112", "ps aux | grep -i bazarr | grep -v grep"))
print("config files:", run("112", "find / -maxdepth 7 -name 'config.ini' 2>/dev/null | grep -v /proc | grep -v /sys"))
print("bazarr dir:", run("112", "find / -maxdepth 5 -name 'bazarr' -type d 2>/dev/null | grep -v /proc"))

# Also get Prowlarr app schema so we know exact field names
import requests, json
key = os.environ["PROWLARR_API_KEY"]
_env_prowlarr_ip = os.environ["PROWLARR_IP"]
r = requests.get(f"http://{_env_prowlarr_ip}:9696/api/v1/applications/schema", headers={"X-Api-Key": key})
if r.status_code == 200:
    schemas = r.json()
    radarr_schema = [s for s in schemas if s.get("implementation") == "Radarr"]
    if radarr_schema:
        print("\nProwlarr Radarr app fields:", [f["name"] for f in radarr_schema[0]["fields"]])
else:
    print(f"Prowlarr schema status: {r.status_code}")
    # Try without /schema
    r2 = requests.get(f"http://{_env_prowlarr_ip}:9696/api/v1/applications", headers={"X-Api-Key": key})
    print("Prowlarr apps:", r2.json())

c.close()
