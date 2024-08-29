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

from fastapi import HTTPException
from server.api.models.mates.mates_ask import (
    MatesAskOutput
)


async def ask_mate(team_slug: str, message: str, mate_username: str):
    """
    Process a message

    - **content**: The content of the message
    """
    # try:
    add_to_log(module_name="OpenMates | API | Process message", state="start", color="yellow")
    add_to_log("Processing an incoming message ...")
    # TODO replace with actual processing of the message

    # TODO: implement task system and dragonfly cache
    # TODO: add processing via AI and send response to messages

    output_message = "Hello, human! You asked me: " + message + ". Your dedicated AI team mate, " + mate_username 

    # prepare the message object
    message = MatesAskOutput(
        message=output_message,
        # TODO: replace with actual counting of tokens and costs
        tokens_used_input=20,
        tokens_used_output=46,
        total_costs_eur=0.003
        )

    add_to_log("Successfully processed the message", state="success")
    raise HTTPException(status_code=500, detail="Internal server error")
    return message


    # except KeyboardInterrupt:
    #     shutdown()

    # except Exception:
    #     process_error("Failed to process the message", traceback=traceback.format_exc())
    #     return {"status": "failed"}