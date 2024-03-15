
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



def verify_token(token: str = Header(None,example="123456789",description="Your API token to authenticate and show you have access to the requested OpenMates server.")):
    try:
        add_to_log(module_name="OpenMates | API | Verify Token", state="start", color="yellow",hide_variables=True)
        add_to_log("Verifying the API token ...")

        if token in load_valid_tokens():
            add_to_log("Success. The API token is valid.",module_name="OpenMates | API | Verify Token", state="success")
            return True
        else:
            add_to_log("The API token is NOT valid.", module_name="OpenMates | API | Verify Token", state="success")
            raise HTTPException(status_code=401, detail="Invalid API Key")

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to get a list of all mates.", traceback=traceback.format_exc())
        raise HTTPException(status_code=401, detail="The API key is invalid")