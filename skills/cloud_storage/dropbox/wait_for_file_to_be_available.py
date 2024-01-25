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

import time
from skills.cloud_storage.dropbox.get_file_exists import get_file_exists


def wait_for_file_to_be_available(filepath: str) -> bool:
    try:
        add_to_log(module_name="Cloud storage | Dropbox", color="blue", state="start")
        add_to_log(f"Wating for file to be available: {filepath} ...")

        while True:
            if get_file_exists(filepath):
                add_to_log(f"File is available: {filepath}", state="success")
                return True
            else:
                time.sleep(1)

    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed to wait for file to be available: '{filepath}'", traceback=traceback.format_exc())
        return False
    
if __name__ == "__main__":
    wait_for_file_to_be_available(filepath="/Documents/Finance/Vouchers/process_these_vouchers/test.pdf")