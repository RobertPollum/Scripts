"""Test YTS mirrors from CT110 using pct exec with a pre-written script."""
import paramiko, os, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def run_host(cmd, timeout=30):
    """Run a command directly on the Proxmox host."""
    chan = ssh.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)
    stdout = chan.makefile("rb").read().decode(errors="replace").strip()
    stderr = chan.makefile_stderr("rb").read().decode(errors="replace").strip()
    chan.close()
    return stdout or stderr

# Write test script to Proxmox host, then run inside CT110 via stdin pipe
test_script = """#!/bin/sh
for host in yts.bz yts.ninjaproxy1.com yts.proxyninja.org movies-api.accel.li; do
    url="https://${host}/api/v2/list_movies.json?limit=1"
    code=$(curl -sL --max-time 12 -o /tmp/yts_test.json -w "%{http_code}" "$url" 2>/dev/null)
    if [ "$code" = "200" ]; then
        status=$(python3 -c "import json,sys; d=json.load(open('/tmp/yts_test.json')); print(d.get('status','?'))" 2>/dev/null)
        echo "OK $host status=$status"
    else
        echo "FAIL $host code=$code"
    fi
done
"""

# Write script to host
with ssh.open_sftp() as sftp:
    with sftp.file("/tmp/yts_test.sh", "w") as f:
        f.write(test_script)

print("=== YTS mirror test from CT110 ===")
result = run_host("chmod +x /tmp/yts_test.sh && pct push 110 /tmp/yts_test.sh /tmp/yts_test.sh && pct exec 110 -- sh /tmp/yts_test.sh", timeout=90)
print(result)

# Also check which apiurl values the definition supports
print()
print("=== YTS definition - valid apiurl hosts ===")
result = run_host("grep -A2 'apiurl\\|default' /var/lib/prowlarr/Definitions/yts.yml 2>/dev/null || pct exec 110 -- grep -A2 'apiurl\\|default' /var/lib/prowlarr/Definitions/yts.yml")
print(result)

ssh.close()
