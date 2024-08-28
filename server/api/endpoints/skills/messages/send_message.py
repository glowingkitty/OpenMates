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

from server.api.models.skills.messages.skills_send_message import MessagesSendInput, MessagesSendOutput, Target, Source, Attachment
from typing import Union, List, Dict, Any

async def send_message(
    message: str,
    source: dict,
    target: dict,
    attachments: List[dict] = []
) -> MessagesSendOutput:
    """
    Send a message to a target provider
    """
    input = MessagesSendInput(
        message=message,
        source=Source(
            bot_name=source.get("bot_name"),
            ai_mate_name=source.get("ai_mate_name")
        ),
        target=Target(
            provider=target.get("provider"),
            group_id=target.get("group_id"),
            channel_id=target.get("channel_id"),
            thread_id=target.get("thread_id")
        ),
        attachments=[Attachment(
            filename=attachment.get("filename"),
            base64_content=attachment.get("base64_content")
        ) for attachment in attachments]
    )

    # TODO: Implement the logic to send the message to the target provider

    return MessagesSendOutput(message_id="1234567890")