"""
Patch Bazarr config.yaml using sed to update sonarr/radarr fields.
Also use Bazarr's venv Python which has PyYAML available.
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

# Find Bazarr's venv Python
out, _ = pct("112", "find /opt/bazarr -name python3 -type f 2>/dev/null | head -3")
print("Bazarr venv pythons:", out)

venv_python = "/opt/bazarr/venv/bin/python3"

# Write patcher to container via pct push
patcher = f"""\
import sys
sys.path.insert(0, '/opt/bazarr/venv/lib/python3.12/site-packages')
import yaml

with open('{CONF_PATH}', 'r') as f:
    cfg = yaml.safe_load(f)

cfg['sonarr']['ip']      = '{SONARR_IP}'
cfg['sonarr']['port']    = 8989
cfg['sonarr']['apikey']  = '{SONARR_KEY}'
cfg['sonarr']['ssl']     = False
cfg['sonarr']['base_url'] = '/'

cfg['radarr']['ip']      = '{RADARR_IP}'
cfg['radarr']['port']    = 7878
cfg['radarr']['apikey']  = '{RADARR_KEY}'
cfg['radarr']['ssl']     = False
cfg['radarr']['base_url'] = '/'

cfg['general']['use_sonarr'] = True
cfg['general']['use_radarr'] = True

with open('{CONF_PATH}', 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

print('sonarr ip:', cfg['sonarr']['ip'])
print('sonarr key:', cfg['sonarr']['apikey'][:8])
print('radarr ip:', cfg['radarr']['ip'])
print('radarr key:', cfg['radarr']['apikey'][:8])
print('PATCHED OK')
"""

sftp = c.open_sftp()
with sftp.open("/tmp/patch_bazarr2.py", "w") as f:
    f.write(patcher)
sftp.close()

_, o, e = c.exec_command("pct push 112 /tmp/patch_bazarr2.py /tmp/patch_bazarr2.py --perms 644")
print("push:", o.read().decode().strip(), e.read().decode().strip())

# Stop Bazarr
print("Stopping Bazarr...")
pct("112", "systemctl stop bazarr 2>/dev/null || true")
time.sleep(3)

# Run with venv python
out2, err2 = pct("112", f"{venv_python} /tmp/patch_bazarr2.py")
print(f"Patcher output: {out2}")
if err2:
    print(f"Patcher error: {err2[:200]}")

# Start Bazarr
print("Starting Bazarr...")
pct("112", "systemctl start bazarr")
time.sleep(10)

c.close()

# Verify via API
print("\n=== Bazarr API verification ===")
r = requests.get(f"http://{BAZARR_IP}:6767/api/system/settings",
                 headers={"X-Api-Key": BAZARR_KEY}, timeout=15)
s = r.json()
sonarr = s.get("sonarr", {})
radarr = s.get("radarr", {})
print(f"sonarr: ip={sonarr.get('ip')} key={'SET' if sonarr.get('apikey') else 'MISSING'}")
print(f"radarr: ip={radarr.get('ip')} key={'SET' if radarr.get('apikey') else 'MISSING'}")
print(f"use_sonarr={s.get('general',{}).get('use_sonarr')} use_radarr={s.get('general',{}).get('use_radarr')}")

if sonarr.get("apikey") and radarr.get("apikey"):
    print("\n✅ Bazarr fully configured with Sonarr + Radarr")
else:
    print("\n⚠️  Bazarr is overwriting config.yaml on startup with defaults")
    print("   This means the service reads config once at boot and resets it.")
    print(f"   Needs manual setup at: http://{os.environ['BAZARR_IP']}:6767 → Settings → Sonarr / Radarr")
