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

# from server import *

import traceback

################

import time
import yaml

config = {}
config_ram_only = {}


def load_config() -> dict:
    try:
        from server import add_to_log, process_error, shutdown, load_secrets
        global config
        global config_ram_only

        if "add_to_log" in globals():
            add_to_log(    state="start",
                file_name=os.path.basename(__file__),
                module_name="Setup",
                color="orange"
            )
            add_to_log(f"Loading config...")

        # Load data from the config.yaml file in the main directory
        full_current_path = os.path.realpath(__file__)
        config_file_path = re.sub('OpenMates.*', 'OpenMates/my_profile/config.yaml', full_current_path)
        if not os.path.exists(config_file_path):
            raise FileNotFoundError(config_file_path+" not found")
        
        # check if the file has been modified recently. If not, return the existing data
        last_modified_time = os.path.getmtime(config_file_path)
        if "last_updated_timestamp" in config and config["last_updated_timestamp"] > last_modified_time:
            if "add_to_log" in globals():
                add_to_log(state="success", message=f"Successfully loaded {len(config)} cached configs")
            return config_ram_only
        
        # else, reload the config
        with open(config_file_path, 'r') as file:
            config = yaml.safe_load(file)
            config_ram_only = config
        
        # load secrets
        secrets = load_secrets()

        # replace {CONTACT_EMAIL} with the actual contact email from .env file
        if secrets and "CONTACT_EMAIL" in secrets:
            config_ram_only["user_agent"]["official"] = config_ram_only["user_agent"]["official"].replace("{CONTACT_EMAIL}", secrets["CONTACT_EMAIL"])

        # load default_modules and use them in the code. Do not save to config, so that they stay seperate from the config.yaml file
        if type(config_ram_only["modules"]["chat_server"]) is list:
            config_ram_only["modules"]["chat_server"] = config_ram_only["modules"]["chat_server"][0]

        if type(config_ram_only["modules"]["large_language_model"]) is list:
            config_ram_only["modules"]["large_language_model"] = config_ram_only["modules"]["large_language_model"][0]

        if type(config_ram_only["modules"]["text_to_image"]) is list:
            config_ram_only["modules"]["text_to_image"] = {
                "default": config_ram_only["modules"]["text_to_image"][0],
                "all_available": config_ram_only["modules"]["text_to_image"],
            }
        
        if type(config_ram_only["modules"]["text_to_speech"]) is list:
            config_ram_only["modules"]["text_to_speech"] = {
                "default": config_ram_only["modules"]["text_to_speech"][0],
                "all_available": config_ram_only["modules"]["text_to_speech"],
            }
        
        if type(config_ram_only["modules"]["transcript"]) is list:
            config_ram_only["modules"]["transcript"] = {
                "default": config_ram_only["modules"]["transcript"][0],
                "all_available": config_ram_only["modules"]["transcript"],
            }

        if type(config_ram_only["modules"]["cloud_storage"]) is list:
            config_ram_only["modules"]["cloud_storage"] = {
                "default": config_ram_only["modules"]["cloud_storage"][0],
                "all_available": config_ram_only["modules"]["cloud_storage"],
            }

        config_ram_only["last_updated_timestamp"] = int(time.time())
        
        if "add_to_log" in globals():
            add_to_log(state="success", message=f"Successfully reloaded {len(config_ram_only)} configs")

        return config_ram_only

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        if "process_error" in globals():
            process_error("Failed to load config", traceback=traceback.format_exc())
        else:
            print(traceback.format_exc())
        return None
    

if __name__ == "__main__":
    load_config()