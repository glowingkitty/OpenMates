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


def save_config(config: dict):
    try:
        full_current_path = os.path.realpath(__file__)
        config_file_path = re.sub('OpenMates.*', 'OpenMates/my_profile/config.yaml', full_current_path)
        if not os.path.exists(config_file_path):
            raise FileNotFoundError(config_file_path+" not found")
        
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)
        with open(config_file_path, 'r') as file:
            data = yaml.load(file)  # Load existing data
        data.update(config)  # Update with new config
        with open(config_file_path, 'w') as file:
            yaml.dump(data, file)  # Write back to file

        add_to_log(state="success", message=f"Successfully saved the config.")

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to save config", traceback=traceback.format_exc())
        return None
    

if __name__ == "__main__":
    config = load_config()

    # add a new entry to the config
    config['another_test'] = 'test'
    save_config(config)