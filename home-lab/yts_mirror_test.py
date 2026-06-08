"""Test YTS mirrors from inside CT110 (Prowlarr) to find one that works."""
import paramiko, os, time, urllib.request, json, urllib.error
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR = f"http://{_env_prowlarr_ip}:9696"
PROWLARR_KEY = os.environ["PROWLARR_API_KEY"]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def run(vmid, cmd, timeout=20):
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

def prowlarr_get(path):
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, headers={"X-Api-Key": PROWLARR_KEY})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def prowlarr_put(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, data=body,
                                  headers={"X-Api-Key": PROWLARR_KEY, "Content-Type": "application/json"})
    req.get_method = lambda: "PUT"
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"{e.code}: {e.read().decode()[:200]}"

# Test candidate YTS API URLs from inside CT110
candidates = [
    "yts.mx",
    "yts.torrentbay.to",
    "yts.proxyninja.org",
    "api.yts.mx",
]

print("=== Testing YTS mirrors from CT110 (Prowlarr LXC) ===")
working = []
for host in candidates:
    url = f"https://{host}/api/v2/list_movies.json?limit=2"
    result = run("110", f"curl -s --max-time 10 -o /dev/null -w '%{{http_code}} %{{url_effective}}' '{url}' 2>&1")
    print(f"  {host}: {result}")
    if result.startswith("200"):
        working.append(host)

# Also try the current accel.li to confirm it's broken
print()
print("=== Confirming accel.li is broken ===")
result = run("110", "curl -s --max-time 10 -o /dev/null -w '%{http_code}' 'https://movies-api.accel.li/api/v2/list_movies.json?limit=2' 2>&1")
print(f"  movies-api.accel.li: {result}")

# Try with actual response for working ones
print()
print("=== Response check for working mirrors ===")
for host in working:
    url = f"https://{host}/api/v2/list_movies.json?limit=2"
    result = run("110", f"curl -s --max-time 10 '{url}' 2>&1 | head -c 200")
    print(f"  {host}: {result[:150]}")

# If nothing found, try dns lookup to see if yts.mx resolves
print()
print("=== DNS resolution of yts.mx from CT110 ===")
print(run("110", "nslookup yts.mx 2>&1"))
print()
print("=== Direct curl to yts.mx ===")
print(run("110", "curl -sv --max-time 10 'https://yts.mx/api/v2/list_movies.json?limit=1' 2>&1 | tail -20", timeout=25))

ssh.close()
