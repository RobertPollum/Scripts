import paramiko, os
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])
_, out, _ = c.exec_command('pct exec 110 -- bash -c "sqlite3 /var/lib/prowlarr/prowlarr.db \'.schema Indexers\'"')
print(out.read().decode())
c.close()
