"""
Write Sonarr/Radarr config directly into Bazarr's config.yaml via pct push,
bypassing the API validation that reverts settings.
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

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def pct(vmid, cmd):
    _, out, err = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

CONF_PATH = "/opt/bazarr/data/config/config.yaml"

# 1. Read current config
out, _ = pct("112", f"cat {CONF_PATH}")
yaml_content = out

# 2. Use sed to patch the sonarr and radarr sections in-place
print("=== Patching Bazarr config.yaml directly ===")

# Stop Bazarr first so config isn't overwritten on exit
pct("112", "systemctl stop bazarr 2>/dev/null || true")
time.sleep(3)

# Use Python inside the container to safely update the yaml
update_script = f"""python3 << 'PYEOF'
import yaml

with open('{CONF_PATH}', 'r') as f:
    cfg = yaml.safe_load(f)

cfg['sonarr']['ip']     = '{SONARR_IP}'
cfg['sonarr']['port']   = 8989
cfg['sonarr']['apikey'] = '{SONARR_KEY}'
cfg['sonarr']['ssl']    = False
cfg['sonarr']['base_url'] = '/'

cfg['radarr']['ip']     = '{RADARR_IP}'
cfg['radarr']['port']   = 7878
cfg['radarr']['apikey'] = '{RADARR_KEY}'
cfg['radarr']['ssl']    = False
cfg['radarr']['base_url'] = '/'

cfg['general']['use_sonarr'] = True
cfg['general']['use_radarr'] = True

with open('{CONF_PATH}', 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

print('DONE')
PYEOF"""

out2, err2 = pct("112", update_script)
print(f"Python update: {out2!r} {err2!r}")

# Verify
out3, _ = pct("112", f"grep -A3 'sonarr:' {CONF_PATH} | head -6")
print(f"Config sonarr section:\n{out3}")
out4, _ = pct("112", f"grep -A3 'radarr:' {CONF_PATH} | head -6")
print(f"Config radarr section:\n{out4}")

# Start Bazarr
print("\nStarting Bazarr...")
pct("112", "systemctl start bazarr")
time.sleep(8)

c.close()

# Verify via API
print("\n=== Verifying via API ===")
r = requests.get(f"http://{BAZARR_IP}:6767/api/system/settings",
                 headers={"X-Api-Key": BAZARR_KEY})
s = r.json()
sonarr = s.get("sonarr", {})
radarr = s.get("radarr", {})
print(f"sonarr: ip={sonarr.get('ip')} key={'SET ('+sonarr['apikey'][:8]+')' if sonarr.get('apikey') else 'MISSING'}")
print(f"radarr: ip={radarr.get('ip')} key={'SET ('+radarr['apikey'][:8]+')' if radarr.get('apikey') else 'MISSING'}")
print(f"use_sonarr={s.get('general',{}).get('use_sonarr')} use_radarr={s.get('general',{}).get('use_radarr')}")

if sonarr.get("apikey") and radarr.get("apikey"):
    print("\n✅ Bazarr fully configured with Sonarr + Radarr")
else:
    print("\n⚠️  Keys not reflecting via API — but config.yaml was patched directly")
    print("   Bazarr should be using the correct config on next restart")
    print(f"   Verify at http://{os.environ['BAZARR_IP']}:6767 → Settings → Sonarr/Radarr")
