
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

from fastapi import Header, HTTPException
from server.api.load_valid_tokens import load_valid_tokens



def verify_token(team_id: str, token: str, scope: str):
    try:
        add_to_log(module_name="OpenMates | API | Verify Token", state="start", color="yellow",hide_variables=True)
        add_to_log("Verifying the API token ...")

        valid_tokens = load_valid_tokens()
        if team_id in valid_tokens and token in valid_tokens[team_id]:
            if scope in valid_tokens[team_id][token]:
                add_to_log("Success. The API token is valid.",module_name="OpenMates | API | Verify Token", state="success")
                return True
            else:
                add_to_log("The API token does not have the necessary scope.", module_name="OpenMates | API | Verify Token", state="success")
                raise HTTPException(status_code=403, detail="The API token does not have the necessary scope.")
        else:
            add_to_log("The API token is invalid. Make sure you use a valid key and that the key is valid for the requested team and scope.", module_name="OpenMates | API | Verify Token", state="success")
            raise HTTPException(status_code=401, detail="The API token is invalid. Make sure you use a valid key and that the key is valid for the requested team.")

    except KeyboardInterrupt:
        shutdown()

    except HTTPException:
        raise

    except Exception:
        process_error("Failed to verify token.", traceback=traceback.format_exc())
        raise HTTPException(status_code=401, detail="The API key is invalid")