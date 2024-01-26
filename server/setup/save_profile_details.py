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

from ruamel.yaml import YAML


def save_profile_details(config: dict):
    try:
        full_current_path = os.path.realpath(__file__)
        config_file_path = re.sub('OpenMates.*', 'OpenMates/my_profile/profile_details.yaml', full_current_path)
        if not os.path.exists(config_file_path):
            raise FileNotFoundError(config_file_path+" not found")
        
        # remove the 'last_updated_timestamp' entry from the config
        if 'last_updated_timestamp' in config:
            config.pop('last_updated_timestamp')

        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)
        with open(config_file_path, 'r') as file:
            data = yaml.load(file)  # Load existing data
        data.update(config)  # Update with new config
        with open(config_file_path, 'w') as file:
            yaml.dump(data, file)  # Write back to file

        add_to_log(state="success", message=f"Successfully saved the profile details.")

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to save profile details", traceback=traceback.format_exc())
        return None
    

if __name__ == "__main__":
    profile_details = load_profile_details()

    # add a new entry to the config
    profile_details['another_test'] = 'test'
    save_profile_details(profile_details)