from fastapi import HTTPException
from server.api.models.mates.mates_ask import (
    MatesAskOutput
)

import logging

logger = logging.getLogger(__name__)


async def ask_mate(team_slug: str, message: str, mate_username: str):
    """
    Process a message
    """
    # try:
    logger.debug("Processing an incoming message ...")
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

    logger.debug("Successfully processed the message")
    return message


    # except KeyboardInterrupt:
    #     shutdown()

    # except Exception:
    #     process_error("Failed to process the message", traceback=traceback.format_exc())
    #     return {"status": "failed"}