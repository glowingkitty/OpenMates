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

from server.api.models.mates import Mate

def get_mate_processing(team_id: str, mate_username: str) -> Mate:
    """
    Get a specific AI team mate on the team
    """
    try:
        add_to_log(module_name="OpenMates | API | Get mate", state="start", color="yellow")
        add_to_log("Getting a specific AI team mate on the team ...")

        # TODO replace with actual list of mates, based on the database
        mate = Mate(username="burton", description="Business development expert")

        add_to_log("Successfully retrieved the requested AI team mate.", state="success")
        return mate

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to get the requested mate.", traceback=traceback.format_exc())
        return []
    
if __name__ == "__main__":
    response = get_mate_processing()
    print(response)