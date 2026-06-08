"""
Patch Bazarr config.yaml using sed — no Python yaml needed.
The yaml structure is simple enough for targeted sed substitutions.
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

def run_host(cmd):
    _, out, err = c.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

# Check if PyYAML is available anywhere
out, _ = pct("112", "find /opt/bazarr -name 'yaml' -type d 2>/dev/null | head -5")
print("yaml dirs in /opt/bazarr:", out)
out2, _ = pct("112", "ls /opt/bazarr/libs/ 2>/dev/null | grep -i yaml")
print("yaml in libs:", out2)

# pip install pyyaml into a temp location
print("\nInstalling PyYAML via pip...")
out3, err3 = pct("112", "pip3 install pyyaml --target /tmp/pylibs -q 2>&1 | tail -3")
print("pip:", out3, err3)

# Write patcher using temp lib path
patcher = f"""\
import sys
sys.path.insert(0, '/tmp/pylibs')
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

print('sonarr.ip=', cfg['sonarr']['ip'])
print('sonarr.apikey=', cfg['sonarr']['apikey'][:8])
print('radarr.ip=', cfg['radarr']['ip'])
print('DONE')
"""

sftp = c.open_sftp()
with sftp.open("/tmp/patch_b4.py", "w") as f:
    f.write(patcher)
sftp.close()

run_host("pct push 112 /tmp/patch_b4.py /tmp/patch_b4.py --perms 644")

print("Stopping Bazarr...")
pct("112", "systemctl stop bazarr 2>/dev/null || true")
time.sleep(3)

out4, err4 = pct("112", "python3 /tmp/patch_b4.py")
print(f"Patcher: {out4}")
if err4:
    print(f"Error: {err4[:200]}")

print("Starting Bazarr...")
pct("112", "systemctl start bazarr")
time.sleep(10)
c.close()

# Verify
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
    print("\n✅ Bazarr fully configured")
else:
    print(f"\n⚠️  Still needs manual config at http://{os.environ['BAZARR_IP']}:6767")
    print(f"   Sonarr → IP: {SONARR_IP}  Port: 8989  Key: {SONARR_KEY}")
    print(f"   Radarr → IP: {RADARR_IP}  Port: 7878  Key: {RADARR_KEY}")
