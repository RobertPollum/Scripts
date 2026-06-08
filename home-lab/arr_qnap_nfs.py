"""
Use sudo with password + qm_export to update QNAP NFS export for Multimedia.
"""
import paramiko, re, time
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

nas_env = {}
for line in (Path(__file__).parent.parent / "nas-ssh" / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        nas_env[k.strip()] = v.strip()

NAS_PASS   = nas_env["QNAP_SSH_PASSWORD"]
PROXMOX_IP = os.environ["PROXMOX_HOST"]

nas = paramiko.SSHClient()
nas.set_missing_host_key_policy(paramiko.AutoAddPolicy())
nas.connect(nas_env["QNAP_SSH_HOST"], username=nas_env["QNAP_SSH_USERNAME"],
            password=NAS_PASS, timeout=15)

def qnap_sudo(cmd):
    """Run command with sudo -S, feeding password via stdin."""
    chan = nas.get_transport().open_session()
    chan.exec_command(f"echo {NAS_PASS!r} | sudo -S {cmd} 2>&1")
    out = b""
    while True:
        chunk = chan.recv(4096)
        if not chunk:
            break
        out += chunk
    decoded = out.decode("utf-8", errors="replace").strip()
    # Strip the sudo password prompt line
    lines = [l for l in decoded.splitlines() if not l.startswith("Password:") and l != ""]
    return "\n".join(lines)

def qnap(cmd):
    _, out, err = nas.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

# ── Test sudo ─────────────────────────────────────────────────────────────────
print("=== Sudo test ===")
out = qnap_sudo("whoami")
print(f"sudo whoami: {out!r}")

# ── Check qm_export usage ─────────────────────────────────────────────────────
print("\n=== qm_export usage ===")
out2, err2 = qnap("qm_export --help 2>&1 || qm_export 2>&1")
print(out2[:300] or err2[:300])

# ── Approach: use sudo to write /etc/exports directly ────────────────────────
print("\n=== Reading current /etc/exports via sudo ===")
exports_raw = qnap_sudo("cat /etc/exports")
print(exports_raw[:600])

# Build patched version
new_lines = []
changed = False
for line in exports_raw.splitlines():
    if ("Multimedia" in line and PROXMOX_IP not in line and
            ("CACHEDEV" in line or "NFSv=4/Multimedia" in line)):
        m = re.search(r'192\.168\.86\.64\(([^)]+)\)', line)
        opts = m.group(1) if m else "sec=sys,rw,async,wdelay,insecure,no_subtree_check,no_root_squash"
        line = line.rstrip() + f" {PROXMOX_IP}({opts})"
        print(f"Patched line: ...{line[-100:]}")
        changed = True
    new_lines.append(line)

if not changed:
    print("Already patched or no Multimedia lines found.")
else:
    new_exports = "\n".join(new_lines) + "\n"

    # Write to /tmp first (no sudo needed), then sudo cp
    chan = nas.get_transport().open_session()
    chan.exec_command("cat > /tmp/exports_patched")
    chan.sendall(new_exports.encode())
    chan.shutdown_write()
    chan.recv_exit_status()
    print("Wrote /tmp/exports_patched")

    # sudo cp
    out3 = qnap_sudo("cp /tmp/exports_patched /etc/exports")
    print(f"sudo cp: {out3!r}")

    # sudo exportfs -ra
    out4 = qnap_sudo("exportfs -ra")
    print(f"sudo exportfs -ra: {out4!r}")

    # Verify
    out5 = qnap_sudo(f"exportfs -v | grep Multimedia | grep {PROXMOX_IP}")
    print(f"Verify: {out5!r}")

nas.close()
