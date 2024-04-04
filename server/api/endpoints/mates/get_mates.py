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
from server.api.models.mates import Mate

def get_mates_processing(team_id: str) -> List[Mate]:
    """
    Get a list of all AI team mates on a team
    """
    try:
        add_to_log(module_name="OpenMates | API | Get mates", state="start", color="yellow")
        add_to_log("Getting a list of all AI team mates in a team ...")

        # TODO replace with actual list of mates, based on the database
        mates = {
            "mates":[
                Mate(username="burton", description="Business development expert"),
                Mate(username="sophia", description="Software development expert"),
                Mate(username="mark", description="Marketing & sales expert")
            ]
        }

        add_to_log("Successfully created a list of all mates in the requested team.", state="success")
        return mates

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to get a list of all mates in the team.", traceback=traceback.format_exc())
        return []
    
if __name__ == "__main__":
    response = get_mates_processing()
    print(response)