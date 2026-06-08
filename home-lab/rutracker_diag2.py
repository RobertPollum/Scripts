"""Diagnose RuTracker add failure - SSH-based, no heavy API calls."""
import paramiko, os, urllib.request, json, urllib.error
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def run(vmid, cmd, timeout=30):
    _, out, err = ssh.exec_command(f"pct exec {vmid} -- bash -c '{cmd}' 2>/dev/null", timeout=timeout)
    stdout = out.read().decode(errors="replace").strip()
    stderr = err.read().decode(errors="replace").strip()
    # Filter LXC deprecation warnings
    stderr = "\n".join(l for l in stderr.splitlines() if "deprecated" not in l.lower())
    return stdout or stderr.strip()

# 1. Find and read the RuTracker definition
print("=== RuTracker definition file ===")
def_files = run("110", "find /var/lib/prowlarr/Definitions -iname 'rutracker*'")
print(f"  Files: {def_files}")

for f in (l for l in def_files.splitlines() if l.startswith("/")):
    print(f"\n  --- {f} ---")
    content = run("110", f"cat {f}", timeout=15)
    # Print key sections
    for line in content.splitlines():
        lower = line.lower()
        if any(x in lower for x in ["login", "username", "password", "captcha", "cloudflare",
                                     "flare", "links:", "- https", "legacylinks", "encoding",
                                     "language", "type:", "cookie"]):
            print(f"  {line}")

# 2. Test reachability of rutracker.org from CT110
print()
print("=== Reachability from CT110 (Prowlarr LXC, via VPN) ===")
for url in ["https://rutracker.org", "https://rutracker.net"]:
    result = run("110",
        f"curl -sL --max-time 12 -o /dev/null -w '%{{http_code}} %{{url_effective}}' '{url}' 2>/dev/null",
        timeout=20)
    print(f"  {url}: {result}")

# 3. Test reachability from CT107 (no VPN) for comparison
print()
print("=== Reachability from CT107 (Radarr, no VPN) ===")
for url in ["https://rutracker.org", "https://rutracker.net"]:
    result = run("107",
        f"curl -sL --max-time 12 -o /dev/null -w '%{{http_code}} %{{url_effective}}' '{url}' 2>/dev/null",
        timeout=20)
    print(f"  {url}: {result}")

# 4. Check Prowlarr recent error logs for rutracker
print()
print("=== Recent Prowlarr logs mentioning rutracker ===")
log_check = run("110",
    "grep -i rutracker /var/lib/prowlarr/logs/prowlarr.txt 2>/dev/null | tail -20 || "
    "journalctl -u prowlarr --no-pager -n 50 2>/dev/null | grep -i rutracker | tail -20",
    timeout=15)
print(log_check or "  (no rutracker log entries found)")

# 5. Check if FlareSolverr is needed and running
print()
print("=== FlareSolverr status (CT114) ===")
result = run("114", "docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null", timeout=10)
print(f"  {result or '(docker not found or no containers)'}")

# 6. Check Prowlarr proxy config via API (small call)
print()
print("=== Prowlarr indexer proxies ===")
_env_prowlarr_ip = os.environ["PROWLARR_IP"]
try:
    req = urllib.request.Request(
        f"http://{_env_prowlarr_ip}:9696/api/v1/indexerProxy",
        headers={"X-Api-Key": os.environ["PROWLARR_API_KEY"]})
    with urllib.request.urlopen(req, timeout=10) as r:
        proxies = json.loads(r.read())
    for p in proxies:
        print(f"  {p['name']} ({p.get('implementationName')}) id={p['id']}")
        for f in p.get("fields", []):
            if f.get("value") and f["name"] in ("host", "port"):
                print(f"    {f['name']}={f['value']}")
except Exception as e:
    print(f"  Error: {e}")

ssh.close()
