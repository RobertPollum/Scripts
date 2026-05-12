#!/usr/bin/env bash
source <(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/misc/build.func)
# Copyright (c) 2021-2026 community-scripts ORG
# Author: community-scripts
# License: MIT | https://github.com/community-scripts/ProxmoxVE/raw/main/LICENSE
# Source: https://waydro.id/

APP="Waydroid"
var_tags="${var_tags:-android;waydroid}"
var_cpu="${var_cpu:-4}"
var_ram="${var_ram:-4096}"
var_disk="${var_disk:-20}"
var_os="${var_os:-debian}"
var_version="${var_version:-12}"
var_unprivileged="${var_unprivileged:-0}"

header_info "$APP"
variables
color
catch_errors

function update_script() {
  header_info
  check_container_storage
  check_container_resources

  msg_info "Updating base system"
  $STD apt-get update
  $STD apt-get upgrade -y
  msg_ok "Base system updated"

  msg_info "Updating Waydroid"
  $STD apt-get install --only-upgrade -y waydroid
  msg_ok "Waydroid updated"

  msg_ok "Updated successfully!"
  exit
}

start
build_container
description

msg_ok "Completed successfully!\n"
echo -e "${CREATING}${GN}${APP} setup has been successfully initialized!${CL}"
echo -e "${INFO}${YW} Access the Waydroid desktop via noVNC at:${CL}"
echo -e "${TAB}${GATEWAY}${BGN}http://${IP}:6080/vnc.html${CL}"
echo -e "${INFO}${YW} Or connect via VNC client to ${IP}:5900${CL}"
echo -e ""
echo -e "${INFO}${YW} NOTE: Run the following on your Proxmox HOST if Waydroid fails to start:${CL}"
echo -e "${TAB}${BGN}modprobe binder_linux devices=binder,hwbinder,vndbinder${CL}"
