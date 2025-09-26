#!/usr/bin/env python3
"""
Tuya Smart Plug Restart Script
Uses tinytuya library to ping an IP address and control a Tuya smart plug
"""

import tinytuya
import subprocess
import platform
import time
import datetime
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
# Load credentials from environment variables
DEVICE_ID = os.getenv("DEVICE_ID")
DEVICE_IP = os.getenv("DEVICE_IP")
LOCAL_KEY = os.getenv("LOCAL_KEY")
TARGET_IP = os.getenv("TARGET_IP")
VERSION = 3.3  # This can remain, or be added to .env if it varies

# --- Validation ---
# Ensure all required environment variables are loaded
if not all([DEVICE_ID, DEVICE_IP, LOCAL_KEY, TARGET_IP]):
    print("Error: One or more environment variables are missing.")
    print("Please ensure DEVICE_ID, DEVICE_IP, LOCAL_KEY, and TARGET_IP are set in your .env file.")
    exit(1)

# Log file
LOG_FILE = os.path.join(os.getcwd(), "tuya_restart.log")

def log_message(message):
    """Log message with timestamp to both console and file"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    
    with open(LOG_FILE, "a") as file:
        file.write(log_entry + "\n")

def ping_ip(ip_address):
    """Ping an IP address using ICMP Echo Request"""
    log_message(f"Attempting to ping {ip_address} with ICMP Echo Request...")
    
    try:
        # Determine the ping command based on the operating system
        if platform.system().lower() == "windows":
            # Windows ping command: -n 1 (send 1 packet), -w 3000 (timeout 3 seconds)
            result = subprocess.run(
                ["ping", "-n", "1", "-w", "3000", ip_address],
                capture_output=True,
                text=True,
                timeout=5
            )
        else:
            # Unix/Linux ping command: -c 1 (send 1 packet), -W 3 (timeout 3 seconds)
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "3", ip_address],
                capture_output=True,
                text=True,
                timeout=5
            )
        
        # Check if ping was successful (return code 0)
        if result.returncode == 0:
            log_message("Ping successful - ICMP Echo Reply received")
            return True
        else:
            log_message("Ping failed - no ICMP Echo Reply received")
            return False
            
    except subprocess.TimeoutExpired:
        log_message("Ping failed - timeout after 5 seconds")
        return False
    except Exception as error:
        log_message(f"Ping failed - error: {str(error)}")
        return False

def connect_to_tuya_device():
    """Connect to the Tuya smart plug"""
    try:
        device = tinytuya.OutletDevice(
            dev_id=DEVICE_ID,
            address=DEVICE_IP,
            local_key=LOCAL_KEY,
            version=VERSION
        )
        
        # Test connection by getting device status
        status = device.status()
        if 'Error' in str(status):
            log_message(f"Failed to connect to Tuya device: {status}")
            return None
        
        log_message("Successfully connected to Tuya device")
        return device
        
    except Exception as error:
        log_message(f"Error connecting to Tuya device: {str(error)}")
        return None

def turn_off_plug(device):
    """Turn off the Tuya smart plug"""
    try:
        log_message("Turning OFF Tuya smart plug...")
        result = device.turn_off()
        
        if 'Error' in str(result):
            log_message(f"Failed to turn off plug: {result}")
            return False
        
        log_message("Successfully turned OFF the smart plug")
        return True
        
    except Exception as error:
        log_message(f"Error turning off plug: {str(error)}")
        return False

def turn_on_plug(device):
    """Turn on the Tuya smart plug"""
    try:
        log_message("Turning ON Tuya smart plug...")
        result = device.turn_on()
        
        if 'Error' in str(result):
            log_message(f"Failed to turn on plug: {result}")
            return False
        
        log_message("Successfully turned ON the smart plug")
        return True
        
    except Exception as error:
        log_message(f"Error turning on plug: {str(error)}")
        return False

def restart_plug(device, off_duration=5):
    """Restart the plug by turning it off, waiting, then turning it back on"""
    log_message(f"Starting plug restart sequence (off for {off_duration} seconds)...")
    
    # Turn off the plug
    if not turn_off_plug(device):
        return False
    
    # Wait for specified duration
    log_message(f"Waiting {off_duration} seconds before turning back on...")
    time.sleep(off_duration)
    
    # Turn on the plug
    if not turn_on_plug(device):
        return False
    
    log_message("Plug restart sequence completed successfully")
    return True

def get_device_status(device):
    """Get and display the current status of the Tuya device"""
    try:
        status = device.status()
        log_message(f"Device status: {status}")
        return status
    except Exception as error:
        log_message(f"Error getting device status: {str(error)}")
        return None

def main():
    """Main function to monitor IP and control Tuya plug"""
    log_message("=== Tuya Smart Plug Restart Script Started ===")
    log_message(f"Target IP to monitor: {TARGET_IP}")
    log_message(f"Tuya device IP: {DEVICE_IP}")
    
    # Connect to Tuya device
    device = connect_to_tuya_device()
    if not device:
        log_message("Failed to connect to Tuya device. Exiting.")
        return
    
    # Get initial device status
    get_device_status(device)
    
    # Test ping
    if ping_ip(TARGET_IP):
        log_message("Initial ping test successful - target is reachable")
        log_message("Script will monitor for connection failures...")
        
        # You can add monitoring loop here if needed
        # For now, just demonstrate the restart functionality
        log_message("Demonstrating plug restart functionality...")
        restart_plug(device, off_duration=3)
        
    else:
        log_message("Initial ping test failed - target is unreachable")
        log_message("Attempting to restart the plug to restore connectivity...")
        
        # Restart the plug since ping failed
        if restart_plug(device):
            log_message("Plug restarted. Waiting 10 seconds before testing connectivity...")
            time.sleep(10)
            
            # Test ping again
            if ping_ip(TARGET_IP):
                log_message("Success! Connectivity restored after plug restart")
            else:
                log_message("Connectivity still not restored after plug restart")
        else:
            log_message("Failed to restart the plug")
    
    log_message("=== Script execution completed ===")

if __name__ == "__main__":
    main()