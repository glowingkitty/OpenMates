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
from dotenv import dotenv_values

secrets = {}


def load_secrets() -> dict:
    try:
        global secrets

        # if add_to_log is not defined, use print
        if "add_to_log" in globals():
            add_to_log(    state="start",
                file_name=os.path.basename(__file__),
                module_name="Setup",
                color="orange"
            )
            add_to_log(f"Loading secrets...")

        # Load data from the config.yaml file in the main directory
        secrets_file_path = re.sub('OpenMates.*', 'OpenMates/my_profile/.env', full_current_path)
        if not os.path.exists(secrets_file_path):
            raise FileNotFoundError(secrets_file_path+" not found")

        # check if secrets file has been modified recently. If not, return the existing data
        last_modified_time = os.path.getmtime(secrets_file_path)
        if "last_updated_timestamp" in secrets_file_path and secrets_file_path["last_updated_timestamp"] > last_modified_time:
            if "add_to_log" in globals():
                add_to_log(state="success", message=f"Successfully loaded {len(secrets)} cached secrets")
            return secrets_file_path
        
        secrets = dict(dotenv_values(secrets_file_path))

        secrets["last_updated_timestamp"] = int(time.time())
        
        if "add_to_log" in globals():
            add_to_log(state="success", message=f"Successfully reloaded {len(secrets)} secrets")

        return secrets

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        if "process_error" in globals():
            process_error("Failed to load secrets", traceback=traceback.format_exc())
        else:
            print(traceback.format_exc())
        return None
    

if __name__ == "__main__":
    load_secrets()