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

from typing import List
from server.api.models import Mate

def get_all_mates() -> List[Mate]:
    """
    Get a list of all AI team mates on the server
    """
    try:
        add_to_log(module_name="OpenMates | API | Get mates", state="start", color="yellow")
        add_to_log("Getting a list of all AI team mates on the server ...")

        # TODO replace with actual list of mates, based on the database
        mates = [
            Mate(name="burton"),
            Mate(name="sophia"),
            Mate(name="mark")
        ]

        add_to_log("Successfully created a list of all mates.", state="success")
        return mates

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to get a list of all mates.", traceback=traceback.format_exc())
        return []
    
if __name__ == "__main__":
    response = get_mates()
    print(response)