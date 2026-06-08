"""Deep network test for YTS from multiple LXCs."""
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
PROXMOX_HOST = os.environ["PROXMOX_HOST"]
PROXMOX_PASS = os.environ["PROXMOX_PASSWORD"]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(PROXMOX_HOST, username="root", password=PROXMOX_PASS)

def run_host(cmd, timeout=30):
    chan = ssh.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)
    stdout = chan.makefile("rb").read().decode(errors="replace").strip()
    stderr = chan.makefile_stderr("rb").read().decode(errors="replace").strip()
    chan.close()
    return stdout or stderr

# Test from Proxmox host itself first
print(f"=== From Proxmox host ({PROXMOX_HOST}) ===")
print("DNS yts.mx:", run_host("nslookup yts.mx 8.8.8.8 2>&1 | grep -E 'Address|NXDOMAIN|server'"))
print("DNS yts.bz:", run_host("nslookup yts.bz 8.8.8.8 2>&1 | grep -E 'Address|NXDOMAIN'"))
print("curl yts.mx:", run_host("curl -sL --max-time 8 -o /dev/null -w '%{http_code}' 'https://yts.mx/api/v2/list_movies.json?limit=1' 2>&1"))
print("curl yts.bz:", run_host("curl -sL --max-time 8 -o /dev/null -w '%{http_code}' 'https://yts.bz/api/v2/list_movies.json?limit=1' 2>&1"))

# Test from CT107 (no VPN)
print()
print("=== From CT107 (Radarr, no VPN) ===")
print("DNS yts.mx:", run_host("pct exec 107 -- nslookup yts.mx 8.8.8.8 2>&1 | grep -E 'Address|NXDOMAIN'"))
print("DNS yts.bz:", run_host("pct exec 107 -- nslookup yts.bz 8.8.8.8 2>&1 | grep -E 'Address|NXDOMAIN'"))
print("HTTP yts.bz:", run_host("pct exec 107 -- curl -sL --max-time 10 -o /dev/null -w '%{http_code}' 'https://yts.bz/api/v2/list_movies.json?limit=1' 2>&1"))

# What IP does yts.bz resolve to?
print()
print("=== IP resolution ===")
print("yts.bz IP:", run_host("nslookup yts.bz 1.1.1.1 2>&1 | grep 'Address' | tail -1"))
print("yts.mx IP:", run_host("nslookup yts.mx 1.1.1.1 2>&1 | grep -E 'Address|NXDOMAIN' | tail -2"))

# Try direct IP for yts.bz
yts_bz_ip = run_host("dig +short yts.bz @1.1.1.1 2>/dev/null | tail -1")
print(f"yts.bz resolved to: {yts_bz_ip}")
if yts_bz_ip and yts_bz_ip.count(".") == 3:
    print("Direct IP curl:", run_host(f"curl -sL --max-time 10 -o /dev/null -w '%{{http_code}}' --resolve 'yts.bz:443:{yts_bz_ip}' 'https://yts.bz/api/v2/list_movies.json?limit=1' 2>&1"))

ssh.close()
