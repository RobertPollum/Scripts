"""
Install FlareSolverr on Proxmox.
Strategy: install Docker inside a new privileged LXC (VMID 114), 
then run FlareSolverr as a Docker container on port 8191.
Finally, register it as a Prowlarr proxy.

FlareSolverr requires Chromium — Docker is the cleanest approach in LXC.
"""
import paramiko, os, time, requests, json
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]
PROWLARR_IP  = os.environ["PROWLARR_IP"]
PROWLARR_KEY = os.environ["PROWLARR_API_KEY"]
FLARE_VMID   = "114"
FLARE_IP     = os.environ["TAILSCALE_IP"]  # will be DHCP, we'll detect it

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def host(cmd, timeout=60):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    return out.read().decode().strip(), err.read().decode().strip()

def pct(vmid, cmd, timeout=120):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}", timeout=timeout)
    return out.read().decode().strip(), err.read().decode().strip()

# ── Check if VMID 114 already exists ─────────────────────────────────────────
print("=== Checking existing containers ===")
out_list, _ = host("pct list")
print(out_list)

if FLARE_VMID in out_list:
    print(f"CT{FLARE_VMID} already exists — skipping creation")
else:
    # ── Find a Debian 12 template ─────────────────────────────────────────────
    print("\n=== Finding Debian 12 template ===")
    templates, _ = host("pveam list local 2>/dev/null | grep -i debian")
    print(templates)
    if not templates:
        # Download one
        print("Downloading Debian 12 template...")
        host("pveam update 2>&1 | tail -3", timeout=30)
        host("pveam download local debian-12-standard_12.7-1_amd64.tar.zst 2>&1 | tail -5", timeout=120)
        templates, _ = host("pveam list local | grep debian-12")
        print(f"Template: {templates}")

    template = templates.strip().splitlines()[-1].split()[0] if templates else "local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst"
    print(f"Using template: {template}")

    # ── Create privileged LXC (Docker needs privileged or nesting+keyctl) ────
    print(f"\n=== Creating CT{FLARE_VMID} (FlareSolverr) ===")
    create_cmd = (
        f"pct create {FLARE_VMID} {template} "
        f"--hostname flaresolverr "
        f"--cores 2 --memory 2048 --swap 512 "
        f"--rootfs local-lvm:8 "
        f"--net0 name=eth0,bridge=vmbr0,ip=dhcp,type=veth "
        f"--ostype debian "
        f"--features nesting=1,keyctl=1 "
        f"--unprivileged 1 "
        f"--onboot 1 "
        f"--password {PROXMOX_PASS!r} "
        f"--start 1"
    )
    out_create, err_create = host(create_cmd, timeout=60)
    print(out_create or err_create)
    time.sleep(8)

# ── Start container if not running ───────────────────────────────────────────
status_out, _ = host(f"pct status {FLARE_VMID}")
print(f"\nCT{FLARE_VMID} status: {status_out}")
if "stopped" in status_out:
    host(f"pct start {FLARE_VMID}")
    time.sleep(6)

# ── Get the container's IP ────────────────────────────────────────────────────
print(f"\n=== Getting CT{FLARE_VMID} IP ===")
for attempt in range(6):
    ip_out, _ = pct(FLARE_VMID, "ip -4 addr show eth0 | grep inet | awk '{print $2}' | cut -d/ -f1")
    if ip_out and ip_out != "":
        FLARE_IP = ip_out.strip()
        break
    time.sleep(5)
print(f"FlareSolverr IP: {FLARE_IP}")

# ── Install Docker ────────────────────────────────────────────────────────────
print(f"\n=== Installing Docker in CT{FLARE_VMID} ===")
docker_check, _ = pct(FLARE_VMID, "docker --version 2>/dev/null || echo NOT_INSTALLED")
print(f"Docker: {docker_check}")

if "NOT_INSTALLED" in docker_check:
    print("Installing Docker...")
    install_out, install_err = pct(FLARE_VMID,
        "apt-get update -qq && "
        "apt-get install -y -qq ca-certificates curl gnupg 2>&1 | tail -3 && "
        "install -m 0755 -d /etc/apt/keyrings && "
        "curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && "
        "chmod a+r /etc/apt/keyrings/docker.gpg && "
        "echo \"deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable\" > /etc/apt/sources.list.d/docker.list && "
        "apt-get update -qq && "
        "apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin 2>&1 | tail -5 && "
        "systemctl enable docker && systemctl start docker && echo DOCKER_OK",
        timeout=300)
    print(install_out[-500:] if install_out else install_err[-300:])
else:
    print("Docker already installed ✅")

# ── Run FlareSolverr container ────────────────────────────────────────────────
print(f"\n=== Starting FlareSolverr container ===")
flare_check, _ = pct(FLARE_VMID, "docker ps -a --filter name=flaresolverr --format '{{.Status}}' 2>/dev/null")
print(f"Existing container: {flare_check or 'none'}")

if "Up" in flare_check:
    print("FlareSolverr already running ✅")
else:
    if flare_check:
        pct(FLARE_VMID, "docker rm -f flaresolverr 2>/dev/null; true")

    run_out, run_err = pct(FLARE_VMID,
        "docker run -d "
        "--name flaresolverr "
        "--restart unless-stopped "
        "-p 8191:8191 "
        "-e LOG_LEVEL=info "
        "-e TZ=America/Detroit "
        "ghcr.io/flaresolverr/flaresolverr:latest 2>&1",
        timeout=120)
    print(run_out or run_err)
    time.sleep(10)

# ── Verify FlareSolverr is up ─────────────────────────────────────────────────
print(f"\n=== Verifying FlareSolverr at {FLARE_IP}:8191 ===")
for attempt in range(6):
    try:
        r = requests.get(f"http://{FLARE_IP}:8191/", timeout=5)
        print(f"  HTTP {r.status_code} ✅")
        break
    except Exception as e:
        print(f"  Attempt {attempt+1}: {e}")
        time.sleep(5)

# ── Register FlareSolverr as Prowlarr indexer proxy ───────────────────────────
print(f"\n=== Registering FlareSolverr in Prowlarr ===")
# Check existing proxies
r_proxies = requests.get(
    f"http://{PROWLARR_IP}:9696/api/v1/indexerProxy",
    headers={"X-Api-Key": PROWLARR_KEY}, timeout=10)
print(f"Existing proxies: {r_proxies.json()}")

existing = [p for p in r_proxies.json() if "flaresolverr" in p.get("name","").lower()]
if existing:
    print(f"FlareSolverr proxy already registered: {existing[0]['name']} ✅")
else:
    payload = {
        "name": "FlareSolverr",
        "implementation": "FlareSolverr",
        "configContract": "FlareSolverrSettings",
        "tags": [],
        "fields": [
            {"name": "host", "value": f"http://{FLARE_IP}:8191"},
            {"name": "requestTimeout", "value": 60}
        ]
    }
    r_add = requests.post(
        f"http://{PROWLARR_IP}:9696/api/v1/indexerProxy",
        headers={"X-Api-Key": PROWLARR_KEY, "Content-Type": "application/json"},
        data=json.dumps(payload), timeout=10)
    if r_add.status_code in (200, 201):
        print(f"  FlareSolverr proxy registered ✅ (id={r_add.json().get('id')})")
    else:
        print(f"  Failed: {r_add.status_code} {r_add.text[:300]}")

c.close()
print(f"\nDone. FlareSolverr at http://{FLARE_IP}:8191")
