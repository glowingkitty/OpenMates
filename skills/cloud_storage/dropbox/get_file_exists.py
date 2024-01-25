################

# Default Imports

################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *

################

import dropbox

def get_file_exists(filepath: str) -> bool:
    try:
        add_to_log(module_name="Cloud storage | Dropbox", color="blue", state="start")
        add_to_log(f"Checking if file exists: {filepath} ...")

        # Load Dropbox access token from secrets
        secrets = load_secrets()
        with dropbox.Dropbox(oauth2_refresh_token=secrets["DROPBOX_REFRESH_TOKEN"], app_key=secrets["DROPBOX_APP_KEY"]) as dbx:
            dbx.files_get_metadata(filepath)
        
        add_to_log(f"File exists: {filepath}", state="success")
        return True
    
    except dropbox.exceptions.ApiError:
        add_to_log(f"File does not exist: {filepath}", state="error")
        return False
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed to check if file exists: '{filepath}'", traceback=traceback.format_exc())
        return False
    
if __name__ == "__main__":
    get_file_exists(filepath="/Documents/Finance/Vouchers/process_these_vouchers/test.pdf")