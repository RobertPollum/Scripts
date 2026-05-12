#!/usr/bin/env bash

# Copyright (c) 2021-2026 community-scripts ORG
# Author: community-scripts
# License: MIT | https://github.com/community-scripts/ProxmoxVE/raw/main/LICENSE
# Source: https://waydro.id/

source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
color
verb_ip6
catch_errors
setting_up_container
network_check
update_os

# -------------------------------------------------------
# STEP 1: Verify binder kernel modules on the host
# -------------------------------------------------------
msg_info "Checking for binder_linux kernel module"
if ! lsmod | grep -q binder_linux; then
  msg_error "binder_linux module is NOT loaded on the Proxmox host!"
  echo -e "  Please run the following on your Proxmox host and then re-run this script:"
  echo -e "    modprobe binder_linux devices=binder,hwbinder,vndbinder"
  echo -e "  To persist across reboots, create /etc/modules-load.d/binder.conf:"
  echo -e "    echo 'binder_linux' > /etc/modules-load.d/binder.conf"
  echo -e "  And create /etc/modprobe.d/binder.conf:"
  echo -e "    echo 'options binder_linux devices=binder,hwbinder,vndbinder' > /etc/modprobe.d/binder.conf"
  exit 1
fi
msg_ok "binder_linux module is loaded"

# -------------------------------------------------------
# STEP 2: Base dependencies
# -------------------------------------------------------
msg_info "Installing base dependencies"
$STD apt-get install -y \
  curl \
  ca-certificates \
  gnupg \
  lsb-release \
  software-properties-common \
  python3 \
  python3-pip \
  git \
  unzip \
  wget \
  adb \
  xfce4 \
  xfce4-goodies \
  dbus-x11 \
  x11-xserver-utils \
  tigervnc-standalone-server \
  tigervnc-common \
  novnc \
  websockify \
  net-tools
msg_ok "Base dependencies installed"

# -------------------------------------------------------
# STEP 3: Install Waydroid
# -------------------------------------------------------
msg_info "Adding Waydroid repository"
export DISTRO="bookworm"
$STD curl -fsSL "https://repo.waydro.id/waydroid.gpg" -o /usr/share/keyrings/waydroid.gpg
echo "deb [signed-by=/usr/share/keyrings/waydroid.gpg] https://repo.waydro.id/ ${DISTRO} main" \
  >/etc/apt/sources.list.d/waydroid.list
$STD apt-get update
msg_ok "Waydroid repository added"

msg_info "Installing Waydroid"
$STD apt-get install -y waydroid
msg_ok "Waydroid installed"

# -------------------------------------------------------
# STEP 4: Initialize Waydroid with GAPPS image
# -------------------------------------------------------
msg_info "Initializing Waydroid with GApps image (this may take a while)"
$STD waydroid init -s GAPPS -f
msg_ok "Waydroid initialized with GApps"

# -------------------------------------------------------
# STEP 5: Install waydroid_script (casualsnek) for Magisk
# -------------------------------------------------------
msg_info "Installing waydroid_script for Magisk patching"
$STD git clone https://github.com/casualsnek/waydroid_script /opt/waydroid_script
$STD pip3 install -r /opt/waydroid_script/requirements.txt
msg_ok "waydroid_script installed at /opt/waydroid_script"

msg_info "Patching Waydroid image with Magisk"
$STD python3 /opt/waydroid_script/main.py install magisk
msg_ok "Magisk patched into Waydroid image"

# -------------------------------------------------------
# STEP 6: Configure VNC server
# -------------------------------------------------------
msg_info "Configuring VNC server"
VNC_PASS="waydroid"
mkdir -p /root/.vnc

# Set VNC password
echo "${VNC_PASS}" | vncpasswd -f >/root/.vnc/passwd
chmod 600 /root/.vnc/passwd

# VNC xstartup for XFCE
cat <<'EOF' >/root/.vnc/xstartup
#!/bin/bash
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export XKL_XMODMAP_DISABLE=1
exec startxfce4
EOF
chmod +x /root/.vnc/xstartup
msg_ok "VNC configured (default password: waydroid)"

# -------------------------------------------------------
# STEP 7: systemd service for VNC
# -------------------------------------------------------
msg_info "Creating VNC systemd service"
cat <<EOF >/etc/systemd/system/vncserver@.service
[Unit]
Description=TigerVNC server %i
After=syslog.target network.target

[Service]
Type=forking
User=root
PAMName=login
PIDFile=/root/.vnc/%H%i.pid
ExecStartPre=-/usr/bin/vncserver -kill :%i > /dev/null 2>&1
ExecStart=/usr/bin/vncserver -depth 24 -geometry 1920x1080 :%i
ExecStop=/usr/bin/vncserver -kill :%i
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

$STD systemctl daemon-reload
$STD systemctl enable vncserver@1.service
$STD systemctl start vncserver@1.service
msg_ok "VNC server service enabled and started"

# -------------------------------------------------------
# STEP 8: systemd service for noVNC (web access)
# -------------------------------------------------------
msg_info "Creating noVNC web service"
cat <<EOF >/etc/systemd/system/novnc.service
[Unit]
Description=noVNC WebSocket proxy
After=network.target vncserver@1.service

[Service]
Type=simple
User=root
ExecStart=/usr/bin/websockify --web=/usr/share/novnc/ 6080 localhost:5901
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

$STD systemctl daemon-reload
$STD systemctl enable novnc.service
$STD systemctl start novnc.service
msg_ok "noVNC web service enabled and started (port 6080)"

# -------------------------------------------------------
# STEP 9: systemd service for Waydroid container
# -------------------------------------------------------
msg_info "Enabling Waydroid container service"
$STD systemctl enable waydroid-container.service
$STD systemctl start waydroid-container.service
msg_ok "Waydroid container service enabled"

# -------------------------------------------------------
# STEP 10: Helper scripts
# -------------------------------------------------------
msg_info "Installing helper scripts"

# Script to install LSPosed + Pixelify after first boot
cat <<'EOF' >/usr/local/bin/waydroid-setup-lsposed
#!/usr/bin/env bash
set -e
echo "==> Downloading LSPosed (zygisk build)..."
LSPOSED_URL=$(curl -fsSL https://api.github.com/repos/LSPosed/LSPosed/releases/latest \
  | grep "browser_download_url.*zygisk.*zip" | head -1 | cut -d'"' -f4)
wget -q "$LSPOSED_URL" -O /tmp/lsposed.zip

echo "==> Pushing LSPosed to Waydroid..."
adb connect localhost:5555
adb push /tmp/lsposed.zip /sdcard/Download/lsposed.zip

echo "==> LSPosed is staged in /sdcard/Download/lsposed.zip"
echo "    Install it via Magisk Manager > Modules > Install from storage"
echo ""
echo "==> Downloading Pixelify GPhotos module..."
PIXELIFY_URL=$(curl -fsSL https://api.github.com/repos/CapnProton/PixelifyGooglePhotos/releases/latest \
  | grep "browser_download_url.*zip" | head -1 | cut -d'"' -f4)
wget -q "$PIXELIFY_URL" -O /tmp/pixelify.zip 2>/dev/null || \
  wget -q "https://github.com/CapnProton/PixelifyGooglePhotos/releases/latest/download/PixelifyGooglePhotos.zip" \
    -O /tmp/pixelify.zip

adb push /tmp/pixelify.zip /sdcard/Download/pixelify.zip
echo "==> Pixelify GPhotos is staged in /sdcard/Download/pixelify.zip"
echo "    Install it via LSPosed Manager after LSPosed is active"
EOF
chmod +x /usr/local/bin/waydroid-setup-lsposed

# Script to mount a host photo directory into Waydroid
cat <<'EOF' >/usr/local/bin/waydroid-mount-photos
#!/usr/bin/env bash
PHOTOS_DIR="${1:-/mnt/photos}"
if [[ ! -d "$PHOTOS_DIR" ]]; then
  echo "Usage: waydroid-mount-photos /path/to/your/photos"
  exit 1
fi
echo "==> Mounting $PHOTOS_DIR into Waydroid shared folder..."
mkdir -p /var/lib/waydroid/overlay/media/0/Pictures/HostPhotos
mount --bind "$PHOTOS_DIR" /var/lib/waydroid/overlay/media/0/Pictures/HostPhotos
echo "==> Photos available in Waydroid at: /sdcard/Pictures/HostPhotos"
echo "    Open Google Photos and select this folder to back up."
EOF
chmod +x /usr/local/bin/waydroid-mount-photos

msg_ok "Helper scripts installed"

# -------------------------------------------------------
# STEP 11: Post-install instructions file
# -------------------------------------------------------
cat <<EOF >/root/WAYDROID-SETUP.txt
=======================================================
  Waydroid LXC - Post-Install Checklist
=======================================================

1. ACCESS DESKTOP
   Open browser: http://<LXC_IP>:6080/vnc.html
   VNC password:  waydroid
   Or VNC client: <LXC_IP>:5900

2. CONNECT ADB (from inside the LXC or over network)
   adb connect localhost:5555
   adb shell

3. INSTALL MAGISK MODULES (LSPosed + Pixelify)
   Run: waydroid-setup-lsposed
   Then inside Waydroid:
     - Open Magisk > Modules > Install from storage
     - Select /sdcard/Download/lsposed.zip
     - Reboot Waydroid
     - Open LSPosed > Install Pixelify from /sdcard/Download/pixelify.zip
     - Enable Pixelify module for Google Photos

4. MOUNT YOUR PHOTO LIBRARY
   Run: waydroid-mount-photos /path/to/your/photos
   Then open Google Photos inside Waydroid and
   select HostPhotos folder for backup.

5. HOST KERNEL MODULE (if Waydroid fails to start)
   On the Proxmox HOST run:
     modprobe binder_linux devices=binder,hwbinder,vndbinder
   Persist via:
     echo 'binder_linux' > /etc/modules-load.d/binder.conf
     echo 'options binder_linux devices=binder,hwbinder,vndbinder' > /etc/modprobe.d/binder.conf

=======================================================
EOF

motd_ssh
customize
cleanup_lxc
