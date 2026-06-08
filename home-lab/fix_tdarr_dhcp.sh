#!/bin/bash
# Kill runaway dhclient and release all secondary IPs on CT108 (tdarr)
set -e

echo "[1] Killing existing dhclient..."
PID=$(cat /run/dhclient.eth0.pid 2>/dev/null || true)
if [ -n "$PID" ]; then
    kill "$PID" 2>/dev/null || true
    sleep 2
fi
pkill -f "dhclient.*eth0" 2>/dev/null || true
sleep 1

echo "[2] Flushing all IPs from eth0..."
ip addr flush dev eth0

echo "[3] Clearing lease file..."
rm -f /var/lib/dhcp/dhclient.eth0.leases

echo "[4] Requesting fresh single DHCP lease..."
dhclient eth0

echo "[5] Current eth0 addresses:"
ip addr show eth0
