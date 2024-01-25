################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

import time
import yaml

profile_details = {}
profile_details_ram_only = {}


def remove_empty_values(data):
    if isinstance(data, dict):
        return {k: remove_empty_values(v) for k, v in data.items() if v and remove_empty_values(v)}
    elif isinstance(data, list):
        return [remove_empty_values(v) for v in data if v and remove_empty_values(v)]
    else:
        return data


def load_profile_details() -> dict:
    try:
        global profile_details
        global profile_details_ram_only

        if "add_to_log" in globals():
            add_to_log(    state="start",
                file_name=os.path.basename(__file__),
                module_name="Setup",
                color="orange"
            )
            add_to_log(f"Loading profile details...")

        # Load data from the profile_details.yaml file in the main directory
        full_current_path = os.path.realpath(__file__)
        profile_details_file_path = re.sub('OpenMates.*', 'OpenMates/my_profile/profile_details.yaml', full_current_path)
        if not os.path.exists(profile_details_file_path):
            raise FileNotFoundError(profile_details_file_path+" not found")
        
        # check if the file has been modified recently. If not, return the existing data
        last_modified_time = os.path.getmtime(profile_details_file_path)
        if "last_updated_timestamp" in profile_details_ram_only and profile_details_ram_only["last_updated_timestamp"] > last_modified_time:
            if "add_to_log" in globals():
                add_to_log(state="success", message=f"Successfully loaded {len(profile_details_ram_only)} cached profile details")
            return profile_details_ram_only
        
        # else, reload the profile_details
        with open(profile_details_file_path, 'r') as file:
            profile_details = yaml.safe_load(file)
            #  remove the empty keys (empty lists, or keys with value None, including keys that have lists with empty strings, including nested keys)
            profile_details_ram_only = remove_empty_values(profile_details)
            

        profile_details_ram_only["last_updated_timestamp"] = int(time.time())
        
        if "add_to_log" in globals():
            add_to_log(state="success", message=f"Successfully reloaded {len(profile_details_ram_only)} profile details")

        return profile_details_ram_only

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        if "process_error" in globals():
            process_error("Failed to load profile details", traceback=traceback.format_exc())
        else:
            print(traceback.format_exc())
        return None
    

if __name__ == "__main__":
    profile = load_profile_details()
    print(profile)