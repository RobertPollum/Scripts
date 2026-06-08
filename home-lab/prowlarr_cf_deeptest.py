"""
Deep test: verify FlareSolverr cookies work for actual data requests,
and check if the CF indexer sites are reachable from CT110 after a solve.
"""
import paramiko, os, json, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def lxc(vmid, cmd, timeout=40):
    _, out, _ = ssh.exec_command(f"pct exec {vmid} -- {cmd}", timeout=timeout)
    return out.read().decode(errors="replace").strip()

_env_flaresolverr_ip = os.environ["FLARESOLVERR_IP"]
FLARE = f"http://{_env_flaresolverr_ip}:8191"

# Step 1: FlareSolverr solve 1337x and show what cookies + User-Agent we get back
print("=== Step 1: FlareSolverr solve 1337x - full response ===")
solve_cmd = (
    f"curl -s --max-time 30 -X POST {FLARE}/v1 "
    f"-H 'Content-Type: application/json' "
    f"-d '{{\"cmd\":\"request.get\",\"url\":\"https://1337x.to/cat/Movies/1/\",\"maxTimeout\":25000}}'"
)
result = lxc("110", solve_cmd, timeout=45)
try:
    d = json.loads(result)
    sol = d.get("solution", {})
    print(f"  status: {d.get('status')}")
    print(f"  HTTP status: {sol.get('status')}")
    print(f"  User-Agent: {sol.get('userAgent','')[:80]}")
    cookies = sol.get("cookies", [])
    print(f"  Cookies ({len(cookies)}):")
    for c in cookies:
        print(f"    {c.get('name')}={str(c.get('value',''))[:30]} domain={c.get('domain')}")
    content_len = len(sol.get("response", ""))
    print(f"  Response body length: {content_len} chars")
    if content_len > 0:
        print(f"  First 200 chars: {sol.get('response','')[:200]}")
except Exception as e:
    print(f"  Parse error: {e}")
    print(f"  Raw: {result[:300]}")

# Step 2: Now use those cookies to make a direct request from CT110 to 1337x
# This simulates what Prowlarr should be doing
print()
print("=== Step 2: Direct request to 1337x using FlareSolverr cookies ===")
solve_cmd2 = (
    f"curl -s --max-time 30 -X POST {FLARE}/v1 "
    f"-H 'Content-Type: application/json' "
    f"-d '{{\"cmd\":\"request.get\",\"url\":\"https://1337x.to/category/Movies/1/\",\"maxTimeout\":25000}}'"
)
result2 = lxc("110", solve_cmd2, timeout=45)
try:
    d2 = json.loads(result2)
    sol2 = d2.get("solution", {})
    print(f"  status={d2.get('status')} HTTP={sol2.get('status')} body_len={len(sol2.get('response',''))}")
    cf_page = "Just a moment" in sol2.get("response", "") or "cloudflare" in sol2.get("response","").lower()
    print(f"  Still CF challenge page: {cf_page}")
except Exception as e:
    print(f"  {e}: {result2[:200]}")

# Step 3: Check Prowlarr logs to see if it's actually routing through FlareSolverr
print()
print("=== Step 3: Recent Prowlarr logs (last 50 lines) ===")
log = lxc("110",
    "tail -50 /var/lib/prowlarr/logs/prowlarr.txt 2>/dev/null",
    timeout=15)
# Filter for relevant lines
relevant = [l for l in log.splitlines() if any(x in l.lower() for x in
    ["flare", "cloudflare", "1337x", "eztv", "kickass", "torrentgalaxy",
     "proxy", "blocked", "challenge", "cookie", "warn", "error"])]
print("\n".join(relevant[-30:]))

# Step 4: Check Prowlarr version and FlareSolverr version compatibility
print()
print("=== Step 4: Version check ===")
import urllib.request
try:
    _env_prowlarr_ip = os.environ["PROWLARR_IP"]
    req = urllib.request.Request(f"http://{_env_prowlarr_ip}:9696/api/v1/system/status",
                                  headers={"X-Api-Key": os.environ["PROWLARR_API_KEY"]})
    with urllib.request.urlopen(req, timeout=10) as r:
        status = json.loads(r.read())
        print(f"  Prowlarr version: {status.get('version')}")
except Exception as e:
    print(f"  Prowlarr: {e}")

flare_ver = lxc("114", "docker inspect flaresolverr --format '{{.Config.Image}}' 2>/dev/null")
print(f"  FlareSolverr image: {flare_ver}")

flare_ver2 = lxc("114",
    "docker exec flaresolverr sh -c 'cat /app/package.json 2>/dev/null | python3 -c "
    "\"import sys,json; print(json.load(sys.stdin).get(\\\"version\\\",\\\"?\\\"))\" 2>/dev/null' 2>/dev/null",
    timeout=10)
print(f"  FlareSolverr app version: {flare_ver2}")

# Step 5: Check if the problem is the CF indexer definitions using wrong URLs
print()
print("=== Step 5: What URLs are the CF indexers actually trying? ===")
for name, def_file in [("1337x", "1337x"), ("EZTV", "eztv"), ("kickasstorrents.to", "kickasstorrents")]:
    links = lxc("110",
        f"grep -A3 'links:\\|legacylinks:' /var/lib/prowlarr/Definitions/{def_file}.yml 2>/dev/null | head -10")
    print(f"\n  {name} ({def_file}.yml) links:")
    for line in links.splitlines():
        if "http" in line or "links:" in line.lower():
            print(f"    {line.strip()}")

ssh.close()
