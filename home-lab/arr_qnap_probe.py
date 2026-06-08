"""Check QNAP sudo access and NFS management tools."""
import paramiko
from pathlib import Path

nas_env = {}
for line in (Path(__file__).parent.parent / "nas-ssh" / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        nas_env[k.strip()] = v.strip()

nas = paramiko.SSHClient()
nas.set_missing_host_key_policy(paramiko.AutoAddPolicy())
nas.connect(nas_env["QNAP_SSH_HOST"], username=nas_env["QNAP_SSH_USERNAME"],
            password=nas_env["QNAP_SSH_PASSWORD"], timeout=15)

def qnap(cmd):
    _, out, err = nas.exec_command(cmd)
    return out.read().decode().strip(), err.read().decode().strip()

print("=== whoami ===")
print(qnap("whoami")[0])
print(qnap("id")[0])

print("\n=== sudo access ===")
out, err = qnap(f"echo '{nas_env['QNAP_SSH_PASSWORD']}' | sudo -S whoami 2>&1")
print(out, err)

print("\n=== QNAP NFS CLI tools ===")
out2, _ = qnap("which nfs-exportd nas_sharedfolder_acl share_nfs qnap_nfs 2>/dev/null; find /usr/local/bin /usr/bin /opt -name '*nfs*' -o -name '*export*' 2>/dev/null | head -10")
print(out2)

print("\n=== QNAP share management API ===")
out3, _ = qnap("find / -name 'qnap_*' -type f 2>/dev/null | head -10")
print(out3)

print("\n=== Check if admin has sudo ===")
out4, err4 = qnap(f"sudo -n exportfs -v 2>&1")
print(out4, err4)

print("\n=== /etc/sudoers ===")
out5, _ = qnap("cat /etc/sudoers 2>/dev/null | head -20")
print(out5)

nas.close()
