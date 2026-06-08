import requests, paramiko, os, time, json
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / ".env")

PROWLARR_IP = os.environ["PROWLARR_IP"]
PROWLARR_KEY = os.environ["PROWLARR_API_KEY"]
BASE = f"http://{PROWLARR_IP}:9696/api/v1"
H = {"X-Api-Key": PROWLARR_KEY}

# Check raw API response
r = requests.get(f"{BASE}/indexer", headers=H, timeout=10)
print(f"HTTP {r.status_code}")
data = r.json()
print(f"Type: {type(data)}, len: {len(data)}")
print("Raw response:")
print(json.dumps(data, indent=2)[:1000])

# Check Prowlarr service status via Proxmox
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])
_, out, _ = c.exec_command('pct exec 110 -- bash -c "systemctl status prowlarr --no-pager -n 5"')
print("\nProwlarr service:")
print(out.read().decode()[:600])

# Check DB directly
_, out2, _ = c.exec_command('pct exec 110 -- bash -c "sqlite3 /var/lib/prowlarr/prowlarr.db \'SELECT Id,Name,Enable,Tags FROM Indexers;\'"')
print("\nDB Indexers:")
print(out2.read().decode())
c.close()
