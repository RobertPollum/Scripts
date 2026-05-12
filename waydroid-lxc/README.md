# Waydroid LXC – Proxmox Community Script

Automates creating a **privileged Debian 12 LXC container** on Proxmox running:

- **Waydroid** (Android 13 + GApps) in a full desktop environment
- **Magisk** (root) patched into the Waydroid image
- **TigerVNC + noVNC** for browser-based desktop access
- Helper scripts for **LSPosed**, **Pixelify Google Photos**, and photo library mounting

This is a drop-in replacement for Windows Subsystem for Android.

---

## Usage

Run this one-liner from the **Proxmox host shell**:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/ProxmoxVED/main/ct/waydroid.sh)"
```

> Replace `YOUR_USERNAME/ProxmoxVED` with your fork path if submitting to community-scripts.

---

## Prerequisites — Proxmox Host

Before running the script, load the required kernel modules on the **Proxmox host**:

```bash
modprobe binder_linux devices=binder,hwbinder,vndbinder
```

To persist across reboots:

```bash
# /etc/modules-load.d/binder.conf
echo "binder_linux" > /etc/modules-load.d/binder.conf

# /etc/modprobe.d/binder.conf
echo "options binder_linux devices=binder,hwbinder,vndbinder" > /etc/modprobe.d/binder.conf
```

Verify:
```bash
lsmod | grep binder
# Should show: binder_linux
```

---

## Container Defaults

| Setting     | Value      |
|-------------|------------|
| OS          | Debian 12  |
| CPU         | 4 cores    |
| RAM         | 4096 MB    |
| Disk        | 20 GB      |
| Privileged  | Yes (required) |
| VNC port    | 5900       |
| noVNC port  | 6080       |

---

## After Install

### 1. Open the Desktop
Navigate to `http://<LXC_IP>:6080/vnc.html` in your browser.
Default VNC password: `waydroid`

### 2. Install LSPosed + Pixelify Google Photos
Run inside the LXC:
```bash
waydroid-setup-lsposed
```
Then inside Waydroid (via the desktop):
1. Open **Magisk** → Modules → Install from storage → `/sdcard/Download/lsposed.zip`
2. Reboot Waydroid: `waydroid session stop && waydroid session start`
3. Open **LSPosed Manager** → Install Pixelify from `/sdcard/Download/pixelify.zip`
4. Enable the Pixelify module scoped to **Google Photos**
5. Reboot Waydroid again

### 3. Mount Your Photo Library
```bash
waydroid-mount-photos /mnt/photos
```
Replace `/mnt/photos` with the path to your photo collection (NFS mount, local dir, etc.).
Inside Google Photos, select `HostPhotos` as the backup folder.

---

## File Structure

```
waydroid-lxc/
├── ct/
│   └── waydroid.sh              # Container creation + variable defaults
├── install/
│   └── waydroid-install.sh      # Full install logic (runs inside LXC)
└── README.md
```

---

## Submitting to community-scripts

Per the contribution guidelines, new scripts go to **ProxmoxVED** first:
1. Fork [ProxmoxVED](https://github.com/community-scripts/ProxmoxVED)
2. Add `ct/waydroid.sh` and `install/waydroid-install.sh`
3. Test on a real Proxmox instance
4. Open a PR in ProxmoxVED for review
