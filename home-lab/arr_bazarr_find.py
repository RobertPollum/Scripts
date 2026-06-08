"""Find Bazarr's Python and locate PyYAML."""
import paramiko, os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ["PROXMOX_HOST"], username="root", password=os.environ["PROXMOX_PASSWORD"])

def pct(vmid, cmd):
    _, out, _ = c.exec_command(f"pct exec {vmid} -- bash -c {repr(cmd)}")
    return out.read().decode().strip()

# What Python runs Bazarr?
print("Bazarr service ExecStart:")
print(pct("112", "systemctl cat bazarr 2>/dev/null | grep -i exec"))

# Find all python executables
print("\nAll pythons:")
print(pct("112", "find / -name 'python*' -type f 2>/dev/null | grep -v proc | grep -v sys | grep -v __pycache__"))

# Check which ones have yaml
print("\nPythons with yaml:")
print(pct("112", "for p in $(find / -name 'python3*' -type f 2>/dev/null | grep -v proc | grep -v __pycache__); do $p -c 'import yaml; print(\"HAS_YAML:\", \"$p\")' 2>/dev/null && echo \"$p has yaml\"; done"))

# Check pip list on system python
print("\nSystem python3 pip list (yaml-related):")
print(pct("112", "python3 -m pip list 2>/dev/null | grep -i yaml"))

c.close()
