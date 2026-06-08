"""Diagnose RuTracker add failure in Prowlarr."""
import urllib.request, json, urllib.error, time

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR = f"http://{_env_prowlarr_ip}:9696"
PROWLARR_KEY = os.environ["PROWLARR_API_KEY"]

def get(path, timeout=20):
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, headers={"X-Api-Key": PROWLARR_KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

# Check Prowlarr is up
print("=== Prowlarr health ===")
try:
    health = get("health", timeout=10)
    print(f"  Up. Issues: {len(health)}")
    for h in health:
        print(f"  [{h['type']}] {h['message'][:100]}")
except Exception as e:
    print(f"  Prowlarr unreachable: {e}")
    print("  Trying to restart via SSH...")
    import paramiko, os
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parent / ".env")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])
    chan = ssh.get_transport().open_session()
    chan.exec_command("pct exec 110 -- systemctl restart prowlarr")
    chan.makefile("rb").read()
    ssh.close()
    print("  Restarted. Waiting 20s...")
    time.sleep(20)
    try:
        health = get("health", timeout=15)
        print(f"  Back up.")
    except Exception as e2:
        print(f"  Still down: {e2}")
        exit(1)

# Get RuTracker schema to see what fields are required
print()
print("=== RuTracker indexer schema ===")
catalog = get("indexer/schema", timeout=30)
rutracker = next((i for i in catalog if "rutracker" in i["name"].lower()), None)
if not rutracker:
    print("RuTracker not found in catalog!")
else:
    print(f"  Name: {rutracker['name']}")
    print(f"  Privacy: {rutracker.get('privacy')}")
    print(f"  definitionName: {rutracker.get('definitionName')}")
    print()
    print("  Required fields:")
    for f in rutracker.get("fields", []):
        if f.get("value") is not None or f.get("type") in ("text", "password", "select"):
            hidden = "(hidden)" if f.get("isHidden") or f.get("type") == "password" else ""
            default = f.get("value", "")
            print(f"    {f['name']:<30} type={f.get('type','?'):<12} default={str(default)[:40]} {hidden}")

# Check current Prowlarr health and proxies
print()
print("=== Prowlarr proxies (FlareSolverr) ===")
proxies = get("indexerProxy")
for p in proxies:
    print(f"  {p['name']} type={p.get('implementationName')} id={p['id']}")

# Check if RuTracker needs FlareSolverr
print()
print("=== RuTracker definition file check ===")
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / ".env")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def run(vmid, cmd, timeout=15):
    chan = ssh.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(f"pct exec {vmid} -- bash -c \"{cmd}\"")
    stdout = chan.makefile("rb").read().decode(errors="replace").strip()
    stderr = chan.makefile_stderr("rb").read().decode(errors="replace").strip()
    chan.close()
    return stdout or stderr

# Find and show RuTracker definition
def_path = run("110", "find /var/lib/prowlarr/Definitions -iname 'rutracker*' 2>/dev/null | head -5")
print(f"  Definition files: {def_path}")
if def_path:
    for f in def_path.splitlines():
        content = run("110", f"grep -E 'login|cloudflare|captcha|username|password|flare' {f} 2>/dev/null | head -20")
        print(f"\n  {f}:")
        print(content)

# Check reachability from CT110
print()
print("=== RuTracker reachability from CT110 ===")
for url in ["https://rutracker.org", "https://rutracker.net"]:
    result = run("110", f"curl -sL --max-time 10 -o /dev/null -w '%{{http_code}} %{{url_effective}}' '{url}' 2>/dev/null")
    print(f"  {url}: {result}")

ssh.close()

# Check recent Prowlarr error logs
print()
print("=== Recent Prowlarr errors (last 20) ===")
logs = get("log?level=error&pageSize=20&sortKey=time&sortDir=desc")
for rec in logs.get("records", []):
    msg = rec.get("message", "")
    print(f"  [{rec.get('time','')[:19]}] {msg[:120]}")
