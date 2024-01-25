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

from fastapi import Depends
from server.api.models import IncomingMessage, OutgoingMessage
from server.api.verify_token import verify_token


def process_message(message: IncomingMessage,token: str = Depends(verify_token)):
    """
    Process a message

    - **content**: The content of the message
    """
    try:
        add_to_log(module_name="OpenMates | API | Process message", state="start", color="yellow")
        add_to_log("Processing an incoming message ...")

        output_message = "Hello, human!"

        # prepare the message object
        message = OutgoingMessage(message=output_message)

        add_to_log("Successfully processed the message", state="success")
        return message


    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to process the message", traceback=traceback.format_exc())
        return {"status": "failed"}
    
if __name__ == "__main__":
    response = process_message(message=IncomingMessage(message="Hello, AI!", team_mate_username="burton"))
    print(response)