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

from skills.intelligence.load_systemprompt import load_systemprompt

def autonomous_web_browsing(goal: str, output_format: str) -> dict:
    try:
        add_to_log(module_name="Web browsing", state="start", color="yellow")
        add_to_log("Starting an autonomous web browsing session ...")

        # load the systemprompt
        planning_systemprompt = load_systemprompt(special_usecase="web_browsing/autonomous_web_browsing/planning")
        
        add_to_log("Successfully fullfilled the goal", state="success")

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to fullfill the goal", traceback=traceback.format_exc())

if __name__ == "__main__":
    autonomous_web_browsing(
        goal="Research what the most commonly used wood screw sizes between 10 and 16mm are and tell me where I can buy them online, ideally from a german online shop. Best even a physical shop in Berlin.", 
        output_format="a list of maximum 10 links"
        )