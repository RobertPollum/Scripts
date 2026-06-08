"""Test CF indexers properly and check if FlareSolverr is being invoked."""
import urllib.request, json, urllib.error, time, paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

_env_prowlarr_ip = os.environ["PROWLARR_IP"]
PROWLARR = f"http://{_env_prowlarr_ip}:9696"
KEY = os.environ["PROWLARR_API_KEY"]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def lxc(vmid, cmd, timeout=20):
    _, out, _ = ssh.exec_command(f"pct exec {vmid} -- {cmd}", timeout=timeout)
    return out.read().decode(errors="replace").strip()

def get(path, timeout=15):
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, headers={"X-Api-Key": KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def post(path, data=None, timeout=60):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(PROWLARR + "/api/v1/" + path, data=body,
                                  headers={"X-Api-Key": KEY, "Content-Type": "application/json"})
    req.get_method = lambda: "POST"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = r.read()
            return json.loads(resp) if resp else {}, None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:300]}"
    except Exception as e:
        return None, str(e)

CF_NAMES = {"eztv", "1337x", "kickasstorrents", "torrentgalaxy"}

# Step 1: Test all indexers via /indexer/testall
print("=== Step 1: POST /indexer/testall ===")
result, err = post("indexer/testall", timeout=120)
if err:
    print(f"  Error: {err[:150]}")
else:
    print(f"  Response type: {type(result)}")
    if isinstance(result, list):
        for item in result:
            name = item.get("name", "?")
            success = item.get("success", item.get("isValid", "?"))
            msg = item.get("message", item.get("validationMessage", ""))
            if any(cf in name.lower() for cf in CF_NAMES) or not success:
                print(f"  {'✓' if success else '✗'} {name}: {msg[:80]}")
    else:
        print(f"  {str(result)[:200]}")

# Step 2: Check Prowlarr logs for FlareSolverr activity
print()
print("=== Step 2: Prowlarr logs - FlareSolverr/CF activity (last 30 lines) ===")
log = lxc("110",
    "grep -i 'flare\\|cloudflare\\|1337x\\|eztv\\|kickass\\|torrentgalaxy' "
    "/var/lib/prowlarr/logs/prowlarr.txt 2>/dev/null | tail -30",
    timeout=15)
print(log or "  (no matching log entries)")

# Step 3: Try a direct Torznab search (not caps) which goes through FlareSolverr
print()
print("=== Step 3: Direct Torznab search test (t=search) ===")
indexers = get("indexer")
cf_idxs = [i for i in indexers if any(cf in i["name"].lower() for cf in CF_NAMES) and i.get("enable")]

for idx in cf_idxs[:2]:  # test first 2 to avoid rate limits
    url = f"{PROWLARR}/{idx['id']}/api?t=search&q=test&apikey={KEY}"
    print(f"  {idx['name']}...", end=" ", flush=True)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=45) as r:
            data = r.read()
            import xml.etree.ElementTree as ET
            items = ET.fromstring(data).findall(".//item")
            print(f"OK — {len(items)} results")
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:100]}")
    except Exception as e:
        print(f"{type(e).__name__}: {str(e)[:80]}")
    time.sleep(5)

# Step 4: Check FlareSolverr logs for activity from CT110
print()
print("=== Step 4: FlareSolverr container logs (CT114) ===")
flare_logs = lxc("114", "docker logs --tail 20 flaresolverr 2>&1", timeout=15)
print(flare_logs)

ssh.close()
