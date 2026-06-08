"""
Use Bazarr's venv Python (which has PyYAML) to patch config.yaml.
"""
import paramiko, os, requests, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

BAZARR_IP  = os.environ["BAZARR_IP"]
BAZARR_KEY = os.environ["BAZARR_API_KEY"]
SONARR_IP  = os.environ["SONARR_IP"]
SONARR_KEY = os.environ["SONARR_API_KEY"]
RADARR_IP  = os.environ["RADARR_IP"]
RADARR_KEY = os.environ["RADARR_API_KEY"]
CONF_PATH  = "/opt/bazarr/data/config/config.yaml"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def pct(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

# Confirm venv python path and yaml availability
out, _ = pct("112", "/opt/bazarr/venv/bin/python3 -c 'import yaml; print(yaml.__version__)'")
print("Venv yaml version:", out)

if not out:
    # Try uv python
    out2, _ = pct("112", "/root/.local/share/uv/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12 -c 'import yaml; print(yaml.__version__)' 2>/dev/null")
    print("uv python yaml:", out2)

# Write patcher script to container
patcher = f"""\
import sys
import yaml

CONF = '{CONF_PATH}'

with open(CONF, 'r') as f:
    cfg = yaml.safe_load(f)

cfg['sonarr']['ip']       = '{SONARR_IP}'
cfg['sonarr']['port']     = 8989
cfg['sonarr']['apikey']   = '{SONARR_KEY}'
cfg['sonarr']['ssl']      = False
cfg['sonarr']['base_url'] = '/'

cfg['radarr']['ip']       = '{RADARR_IP}'
cfg['radarr']['port']     = 7878
cfg['radarr']['apikey']   = '{RADARR_KEY}'
cfg['radarr']['ssl']      = False
cfg['radarr']['base_url'] = '/'

cfg['general']['use_sonarr'] = True
cfg['general']['use_radarr'] = True

with open(CONF, 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

print('sonarr ip:', cfg['sonarr']['ip'])
print('sonarr apikey:', cfg['sonarr']['apikey'][:8])
print('radarr ip:', cfg['radarr']['ip'])
print('radarr apikey:', cfg['radarr']['apikey'][:8])
print('use_sonarr:', cfg['general']['use_sonarr'])
print('DONE')
"""

sftp = c.open_sftp()
with sftp.open("/tmp/patch_bazarr3.py", "w") as f:
    f.write(patcher)
sftp.close()

_, o, e = c.exec_command("pct push 112 /tmp/patch_bazarr3.py /tmp/patch_bazarr3.py --perms 644")
print("push:", o.read().decode().strip(), e.read().decode().strip())

print("Stopping Bazarr...")
pct("112", "systemctl stop bazarr 2>/dev/null || true")
time.sleep(3)

# Run with venv python
out2, err2 = pct("112", "/opt/bazarr/venv/bin/python3 /tmp/patch_bazarr3.py")
print(f"Result: {out2}")
if err2:
    print(f"Errors: {err2[:300]}")

print("Starting Bazarr...")
pct("112", "systemctl start bazarr")
time.sleep(10)

c.close()

# Verify via API
print("\n=== Bazarr API verification ===")
for attempt in range(3):
    try:
        r = requests.get(f"http://{BAZARR_IP}:6767/api/system/settings",
                         headers={"X-Api-Key": BAZARR_KEY}, timeout=15)
        break
    except Exception:
        time.sleep(5)

s = r.json()
sonarr = s.get("sonarr", {})
radarr = s.get("radarr", {})
print(f"sonarr: ip={sonarr.get('ip')} key={'SET' if sonarr.get('apikey') else 'MISSING'}")
print(f"radarr: ip={radarr.get('ip')} key={'SET' if radarr.get('apikey') else 'MISSING'}")
print(f"use_sonarr={s.get('general',{}).get('use_sonarr')} use_radarr={s.get('general',{}).get('use_radarr')}")

if sonarr.get("apikey") and radarr.get("apikey"):
    print("\n✅ Bazarr fully configured with Sonarr + Radarr")
else:
    print("\n⚠️  Bazarr resets config on startup — needs manual UI config")
    print(f"   http://{os.environ['BAZARR_IP']}:6767 → Settings → Sonarr")
    print(f"   IP: {SONARR_IP}, Port: 8989, API Key: {SONARR_KEY}")
    print(f"   http://{os.environ['BAZARR_IP']}:6767 → Settings → Radarr")
    print(f"   IP: {RADARR_IP}, Port: 7878, API Key: {RADARR_KEY}")
