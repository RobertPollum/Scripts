"""Read client.conf and a sample .ovpn to understand what needs to be combined."""
import paramiko
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(Path(__file__).parent / ".env")

HOST = os.environ["PROXMOX_HOST"]
USER = os.environ["PROXMOX_USER"].split("@")[0]
PASS = os.environ["PROXMOX_PASSWORD"]
LXC_ID = "109"


def get_client():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=10)
    return c


def run(client, cmd, label=None):
    _, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    print(f"\n$ {label or cmd}")
    if out:
        print(out, end="")
    if err:
        print("[err]", err, end="")
    return out, err


def lxc(client, inner_cmd, label=None):
    return run(client, f"pct exec {LXC_ID} -- bash -c {repr(inner_cmd)}", label=label or inner_cmd)


client = get_client()

lxc(client, "cat /etc/openvpn/client.conf", label="client.conf")
lxc(client, "cat /root/openvpn/us_east.ovpn", label="us_east.ovpn (sample)")
lxc(client, "cat /root/pass.txt", label="pass.txt")

client.close()
