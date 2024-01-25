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

import traceback

################

import time
import yaml

valid_tokens = {}
valid_tokens_ram_only = {}


def load_valid_tokens() -> dict:
    try:
        global valid_tokens
        global valid_tokens_ram_only

        # Load data from the valid_api_tokens.yaml file in the main directory
        full_current_path = os.path.realpath(__file__)
        tokens_file_path = re.sub('OpenMates.*', 'OpenMates/my_server/valid_api_tokens.yaml', full_current_path)
        if not os.path.exists(tokens_file_path):
            raise FileNotFoundError(tokens_file_path + " not found")

        # check if the file has been modified recently. If not, return the existing data
        last_modified_time = os.path.getmtime(tokens_file_path)
        if "last_updated_timestamp" in valid_tokens and valid_tokens["last_updated_timestamp"] > last_modified_time:
            add_to_log(state="success", message=f"Successfully loaded {len(valid_tokens['tokens'])} cached tokens")
            return valid_tokens_ram_only['tokens']

        # else, reload the tokens
        with open(tokens_file_path, 'r') as file:
            valid_tokens = yaml.safe_load(file)
            valid_tokens_ram_only = valid_tokens

        valid_tokens_ram_only["last_updated_timestamp"] = int(time.time())

        add_to_log(module_name="OpenMates | API | Load valid tokens", state="success", message=f"Successfully reloaded {len(valid_tokens_ram_only['tokens'])} tokens")

        return valid_tokens_ram_only['tokens']

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        if "process_error" in globals():
            process_error("Failed to load valid tokens", traceback=traceback.format_exc())
        else:
            print(traceback.format_exc())
        return None


if __name__ == "__main__":
    tokens = load_valid_tokens()
    print(tokens)