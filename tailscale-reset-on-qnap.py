## Credit to https://www.geeksforgeeks.org/python/python-script-to-monitor-network-connection-and-saving-into-log-file/ for 
## network pinging code
import os
import sys
import socket
import datetime
import time
from fabric import Connection


FILE = os.path.join(os.getcwd(), "networkinfo.log")

# creating log file in the currenty directory
# ??getcwd?? get current directory,
# os function, ??path?? to specify path


def ping():
    # Send ICMP Echo Request packet to ping a particular IP
    import subprocess
    import platform
    
    host = "192.168.86.51"
    print(f"Attempting to ping {host} with ICMP Echo Request...")
    
    try:
        # Determine the ping command based on the operating system
        if platform.system().lower() == "windows":
            # Windows ping command: -n 1 (send 1 packet), -w 3000 (timeout 3 seconds)
            result = subprocess.run(
                ["ping", "-n", "1", "-w", "3000", host],
                capture_output=True,
                text=True,
                timeout=5
            )
        else:
            # Unix/Linux ping command: -c 1 (send 1 packet), -W 3 (timeout 3 seconds)
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "3", host],
                capture_output=True,
                text=True,
                timeout=5
            )
        
        # Check if ping was successful (return code 0)
        if result.returncode == 0:
            print("Ping successful - ICMP Echo Reply received")
            return True
        else:
            print("Ping failed - no ICMP Echo Reply received")
            return False
            
    except subprocess.TimeoutExpired:
        print("Ping failed - timeout after 5 seconds")
        return False
    except Exception as error:
        print(f"Ping failed - error: {str(error)}")
        return False


def calculate_time(start, stop):
  
    # calculating unavailability
    # time and converting it in seconds
    difference = stop - start
    seconds = float(str(difference.total_seconds()))
    return str(datetime.timedelta(seconds=seconds)).split(".")[0]


def first_check():
    # to check if the system was already
    # connected to an internet connection

    if ping():
        # if ping returns true
        live = "\nCONNECTION ACQUIRED\n"
        print(live)
        connection_acquired_time = datetime.datetime.now()
        acquiring_message = "connection acquired at: " + \
            str(connection_acquired_time).split(".")[0]
        print(acquiring_message)

        with open(FILE, "a") as file:
          
            # writes into the log file
            file.write(live)
            file.write(acquiring_message)

        return True

    else:
        # if ping returns false
        not_live = "\nCONNECTION NOT ACQUIRED\n"
        print(not_live)

        with open(FILE, "a") as file:
          
            # writes into the log file
            file.write(not_live)
        return False

def reset_tailscale():
    """SSH into QNAP and restart Tailscale with accept-routes=false"""
    try:
        # Replace with your QNAP credentials
        host = "192.168.86.51"  # Using same IP from ping() function
        username = "RobertMPollum"  # Replace with your username
        password = "AN4$BlastToThePast"  # Replace with your password

        # Create SSH connection
        conn = Connection(
            host=host,
            user=username,
            connect_kwargs={
                "password": password
            }
        )

        # Execute Tailscale command
        # cmd = "cd /share/CACHEDEV1_DATA/.qpkg/Tailscale && ./tailscale up --accept-routes=false"
        cmd = "ls -la"
        result = conn.run(cmd, hide=True)

        if result.ok:
            print("Tailscale reset successful")
            
            # List directories after successful connection
            list_cmd = "ls -la /share/CACHEDEV1_DATA/.qpkg"
            dir_result = conn.run(list_cmd, hide=True)
            
            if dir_result.ok:
                dir_listing = dir_result.stdout.strip()
                print("Directory listing after Tailscale reset:")
                print(dir_listing)
                
                # Log the directory listing
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log_message = f"\n[{timestamp}] Tailscale directory listing after reset:\n{dir_listing}\n"
                
                with open(FILE, "a") as file:
                    file.write(log_message)
            else:
                print("Failed to list directories")
                error_message = f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Failed to list Tailscale directory\n"
                with open(FILE, "a") as file:
                    file.write(error_message)
            
            return True
        else:
            print("Tailscale reset failed")
            return False

    except Exception as e:
        print(f"Error resetting Tailscale: {str(e)}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

def main():
  
    # main function to call functions
    monitor_start_time = datetime.datetime.now()
    monitoring_date_time = "monitoring started at: " + \
        str(monitor_start_time).split(".")[0]

    if first_check():
        # if true
        print(monitoring_date_time)
        # monitoring will only start when
        # the connection will be acquired

    else:
        # if false
        attempt_count = 1
        while True:
          
            # infinite loop to see if the connection is acquired
            print(f"Connection attempt #{attempt_count}")
            if not ping():
                
                # if connection not acquired
                print("Connection failed, retrying in 1 second...")
                attempt_count += 1
                time.sleep(1)
            else:
                
                # if connection is acquired
                print(f"Connection established after {attempt_count} attempts")
                first_check()
                print(monitoring_date_time)
                break

    with open(FILE, "a") as file:
      
        # write into the file as a into networkinfo.log,
        # "a" - append: opens file for appending,
        # creates the file if it does not exist???
        file.write("\n")
        file.write(monitoring_date_time + "\n")

    # while True: #
      
    # infinite loop, as we are monitoring
    # the network connection till the machine runs
    print("Checking connection status...")
    down_time = datetime.datetime.now()
    if not ping():
        
        # if false: the loop will execute after every 5 seconds
        # fail message will be displayed
        
        fail_msg = "disconnected at: " + str(down_time).split(".")[0]
        print(fail_msg)
        
        with open(FILE, "a") as file:
            # writes into the log file
            file.write(fail_msg + "\n")

        time.sleep(5)

    else:

        # Add Tailscale reset attempt
        reset_tailscale()

        reconnect_attempt = 1
        while not ping():
            
            # infinite loop, will run till ping() return true
            print(f"Reconnection attempt #{reconnect_attempt}")
            reconnect_attempt += 1
            time.sleep(1)

        up_time = datetime.datetime.now()
        
        # after loop breaks, connection restored
        uptime_message = "connected again: " + str(up_time).split(".")[0]

        down_time = calculate_time(down_time, up_time)
        unavailablity_time = "connection was unavailable for: " + down_time

        print(uptime_message)
        print(unavailablity_time)

        with open(FILE, "a") as file:
            
            # log entry for connection restoration time,
            # and unavailability time
            file.write(uptime_message + "\n")
            file.write(unavailablity_time + "\n")

main()