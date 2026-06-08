"""Find a working YTS API from CT110, trying more mirrors with redirect following."""
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def run(vmid, cmd, timeout=25):
    chan = ssh.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(f"pct exec {vmid} -- bash -c \"{cmd}\"")
    try:
        stdout = chan.makefile("rb").read().decode(errors="replace").strip()
        stderr = chan.makefile_stderr("rb").read().decode(errors="replace").strip()
    except Exception:
        stdout, stderr = "", "timeout"
    chan.close()
    return stdout or stderr

# Test with -L (follow redirects) and actual JSON check
candidates = [
    "yts.mx",
    "yts.am",
    "yts.pm",
    "yts.rs",
    "yts.ag",
    "yts-api.org",
    "movies-api.accel.li",   # current (broken)
]

print("=== YTS mirror test from CT110 (with redirect follow) ===")
working = []
for host in candidates:
    url = f"https://{host}/api/v2/list_movies.json?limit=1"
    # Follow redirects, check for JSON status=ok
    result = run("110", f"curl -sL --max-time 12 '{url}' 2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin); print('OK status=' + d.get('status','?') + ' movies=' + str(d.get('data',{{}}).get('movie_count','?')))\" 2>/dev/null || echo FAIL")
    print(f"  {host}: {result}")
    if result.startswith("OK"):
        working.append(host)

print()
print(f"Working mirrors: {working}")

# Also check Prowlarr's indexer definition file to see what apiurl options exist
print()
print("=== Prowlarr YTS indexer definition ===")
result = run("110", "find /var/lib/prowlarr -name 'yts.yml' -o -name 'yts.yaml' 2>/dev/null | head -3")
print(f"  Definition file: {result}")
if result:
    content = run("110", f"grep -A5 'apiurl\\|links\\|encoding\\|url' {result.split()[0]} 2>/dev/null | head -30")
    print(content)

ssh.close()
