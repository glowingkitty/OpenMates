################

# Default Imports

################
import sys
import os
import re
import datetime
import traceback
import signal

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################


import asyncio
import aiohttp


async def fetch_status(device_name: str, ip: str, timeout: int = 15):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{ip}/json/info", timeout=timeout) as response:
                if response.status != 200:
                    raise Exception(f"Failed to fetch device info for {device_name} at {ip}")
    except Exception:
        add_to_log(f"Failed to connect to device {device_name} at {ip}", state="error")


async def check_devices_online(device_dict: dict, check_delay_seconds: int = 5, check_duration_minutes: int = None):
    try:
        add_to_log(module_name="GlowOS", color="blue", state="start")
        add_to_log("Starting to check devices and see if they are available on the network ...")
        
        start_time = datetime.datetime.now()
        add_to_log(f"Check started at {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        def signal_handler(sig, frame):
            add_to_log("KeyboardInterrupt (ID: {}) has been caught.".format(sig))
            end_time = datetime.datetime.now()
            add_to_log(f"Check ended at {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        
        while True:
            tasks = [fetch_status(device_name, ip) for device_name, ip in device_dict.items()]
            await asyncio.gather(*tasks)
            
            await asyncio.sleep(check_delay_seconds)
            if check_duration_minutes is not None:
                if (datetime.datetime.now() - start_time).total_seconds() > check_duration_minutes * 60:
                    break
        
        end_time = datetime.datetime.now()
        add_to_log(f"Check ended at {end_time.strftime('%Y-%m-%d %H:%M:%S')}", state="success")
    
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)
    
    except Exception:
        process_error("Failed during the device online check", traceback=traceback.format_exc())

if __name__ == "__main__":
    device_dict = {
        "electronics area sign .local":     "beexcellent.local",
        "electronics area sign IP":         "192.168.42.119",
        "glowtower .local":                 "glowtower.local",
        "glowtower IP":                     "192.168.43.203",
    }
    asyncio.run(check_devices_online(device_dict))