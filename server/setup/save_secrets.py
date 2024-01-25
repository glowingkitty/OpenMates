################
# Default Imports
################
import sys
import os
import re
from dotenv import set_key

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

################

from server.logging.add_to_log import add_to_log
from server.error.process_error import process_error
from server.shutdown.shutdown import shutdown

import traceback

def save_secrets(secrets: dict):
    try:
        add_to_log(module_name="Setup", color="yellow", state="start", hide_variables=True)
        add_to_log("Saving secrets to .env file ...")

        # Define the path to the .env file
        secrets_file_path = re.sub('OpenMates.*', 'OpenMates/my_profile/.env', full_current_path)
        
        # Check if the .env file exists, if not, create it
        if not os.path.exists(secrets_file_path):
            open(secrets_file_path, 'a').close()
        
        # Save each secret to the .env file
        for key, value in secrets.items():
            if key == 'last_updated_timestamp':
                continue
            if not isinstance(value, str):
                value = str(value)
            set_key(secrets_file_path, key, value)
        
        add_to_log("Successfully saved secrets to .env file", state="success")
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to save secrets to .env file", traceback=traceback.format_exc())

if __name__ == "__main__":
    # Example usage:
    save_secrets({'TEST': 'your-api-key', 'ANOTHER_SECRET': 'another-secret-value'})