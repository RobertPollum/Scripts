"""Fix books dir permissions on NAS and set Readarr root folder."""
import paramiko, requests, json, time
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

home_env = {}
for line in (Path(__file__).parent / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        home_env[k.strip()] = v.strip()

nas_env = {}
for line in (Path(__file__).parent.parent / "nas-ssh" / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        nas_env[k.strip()] = v.strip()

READARR_IP = os.environ["READARR_IP"]; READARR_KEY = os.environ["READARR_API_KEY"]
NAS_PASS   = nas_env["QNAP_SSH_PASSWORD"]

# ── Check books dir perms on NAS via SSH ─────────────────────────────────────
print("=== NAS: books dir permissions ===")
nas = paramiko.SSHClient()
nas.set_missing_host_key_policy(paramiko.AutoAddPolicy())
nas.connect(nas_env["QNAP_SSH_HOST"], username=nas_env["QNAP_SSH_USERNAME"],
            password=NAS_PASS, timeout=15)

def qnap(cmd):
    _, out, err = nas.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

def qnap_sudo(cmd):
    chan = nas.get_transport().open_session()
    chan.exec_command(f"echo {NAS_PASS!r} | sudo -S {cmd} 2>&1")
    out = b""
    while True:
        chunk = chan.recv(4096)
        if not chunk:
            break
        out += chunk
    lines = [l for l in out.decode(errors="replace").strip().splitlines()
             if not l.startswith("Password:") and l]
    return "\n".join(lines)

# Check current ownership/perms
out, _ = qnap("ls -la /share/CACHEDEV1_DATA/Multimedia/Videos/ | grep -E 'books|movies|television'")
print(out)

# Fix: chmod 777 and chown 1000:100 (matching movies/television) on books
print("\n=== Fixing books permissions ===")
out2 = qnap_sudo("chmod 777 /share/CACHEDEV1_DATA/Multimedia/Videos/books && chown 1000:100 /share/CACHEDEV1_DATA/Multimedia/Videos/books && echo OK")
print(f"chmod/chown: {out2}")

# Verify
out3, _ = qnap("ls -la /share/CACHEDEV1_DATA/Multimedia/Videos/ | grep books")
print(f"After fix: {out3}")

nas.close()

# ── Test write from Readarr container now ─────────────────────────────────────
print("\n=== Test write from Readarr ===")
prox = paramiko.SSHClient()
prox.set_missing_host_key_policy(paramiko.AutoAddPolicy())
prox.connect(home_env["PROXMOX_HOST"], username="root", password=home_env["PROXMOX_PASSWORD"])

def pct(vmid, cmd):
    _, out, err = prox.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip(), err.read().decode().strip()

out4, _ = pct("113", "touch /data/books/.test 2>&1 && rm -f /data/books/.test && echo WRITABLE || echo READONLY")
print(f"Readarr /data/books: {out4}")

if "WRITABLE" in out4:
    print("\n=== Setting Readarr root folder ===")
    time.sleep(2)
    r = requests.get(f"http://{READARR_IP}:8787/api/v1/rootfolder",
                     headers={"X-Api-Key": READARR_KEY}, timeout=10)
    if any(x["path"] == "/data/books" for x in r.json()):
        print("  Already set ✅")
    else:
        r2 = requests.post(f"http://{READARR_IP}:8787/api/v1/rootfolder",
                           headers={"X-Api-Key": READARR_KEY, "Content-Type": "application/json"},
                           data=json.dumps({"path": "/data/books"}), timeout=10)
        print(f"  {r2.status_code} {'✅' if r2.status_code in (200,201) else r2.text[:200]}")
else:
    print("Still read-only — permissions fix didn't take effect yet")

prox.close()
