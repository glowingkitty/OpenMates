import os
import re
import json
import traceback
import sys
import os
import re


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('workflows.*', '', full_current_path)
sys.path.append(main_directory)

from server.error.process_error import process_error

def add_to_webinstaller_devices_list(env,version,chip_family="ESP32-S3"):
    try:
        product_names = {
            "glowcore_v3_0": "GlowCore v3.0",
            "glowlight_glowtower_v2_0": "GlowLight/GlowTower v2.0"
        }

        # Get the full path of the current file
        full_current_path = os.path.realpath(__file__)

        # Replace "OpenMates" and everything that follows with "GlowOS-Webinstaller"
        glowos_webinstaller_dir = re.sub('OpenMates.*', 'GlowOS-Webinstaller', full_current_path)

        if not os.path.exists(glowos_webinstaller_dir):
            raise Exception(glowos_webinstaller_dir+" not found")
        
        # read the devices.json file from the webinstaller folder
        with open(os.path.join(glowos_webinstaller_dir, "devices.json"), 'r') as f:
            devices = json.load(f)

        # check if the device is already in the list
        device_in_list = False
        for device in devices["devices"]:
            if device["tag"] == env:
                device_in_list = True

                # check if the project is already in the list
                project_in_list = False
                for project in device["projects"]:
                    if project["tag"] == f"{env}__glowos_{version}_merged":
                        project_in_list = True
                        break

                # if the project is not in the list, add it
                if not project_in_list:
                    device["projects"].append({
                        "tag": f"{env}__glowos_{version}_merged",
                        "name": f"GlowOS {version.replace('_', '.')}"
                    })
                    print(f"Project {env}__glowos_{version}_merged added to devices.json")

                break

        # if the device is not in the list, add it
        if not device_in_list:
            devices["devices"].append({
                "tag": env,
                "chipfamily": chip_family,
                "name": product_names[env],
                "projects": [{
                    "tag": f"{env}__glowos_{version}_merged",
                    "name": f"GlowOS {version.replace('_', '.')}"
                }]
            })
            print(f"Device {env} added to devices.json")

        # then write to webinstaller manifest folder as {env}__glowos_{version}_merged.json
        with open(os.path.join(glowos_webinstaller_dir, "devices.json"), 'w') as f:
            json.dump(devices, f, indent=None)

        print(f"Device {env}__glowos_{version}_merged.json added to devices.json")
        
    except Exception:
        process_error(f"While adding the device {env}__glowos_{version}_merged.json to devices.json", traceback=traceback.format_exc())


if __name__ == "__main__":
    add_to_webinstaller_devices_list("glowcore_v3_0","0.16.1")