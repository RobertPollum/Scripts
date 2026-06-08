"""Read Jellyseerr settings.json from CT106 to get API key and connection config."""
import paramiko
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_USER = 'root'
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]
CT_ID = 106


def pct_exec(ssh, cmd):
    full = f"pct exec {CT_ID} -- bash -c \"{cmd}\""
    _, stdout, stderr = ssh.exec_command(full)
    return stdout.read().decode().strip(), stderr.read().decode().strip()


ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(PROXMOX_HOST, username=PROXMOX_USER, password=PROXMOX_PASS, timeout=10)

out, _ = pct_exec(ssh, "cat /opt/seerr/config/settings.json")
ssh.close()

try:
    cfg = json.loads(out)
    print("API Key:", cfg.get('apiKey', 'NOT FOUND'))
    print("Radarr config:", json.dumps(cfg.get('radarr', []), indent=2))
    print("Sonarr config:", json.dumps(cfg.get('sonarr', []), indent=2))
    # Print full config minus sensitive fields for context
    for k, v in cfg.items():
        if k not in ('radarr', 'sonarr', 'notifications'):
            print(f"{k}: {v}")
except Exception as e:
    print("Parse error:", e)
    print("Raw:", out[:500])
