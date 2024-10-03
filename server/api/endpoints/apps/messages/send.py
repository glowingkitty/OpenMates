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

from server.api import *
################

from server.api.models.apps.messages.skills_send_message import MessagesSendInput, MessagesSendOutput, Target, Attachment
from typing import Union, List, Dict, Any

from server.api.endpoints.apps.messages.providers.discord.send import send as send_discord
# from server.api.endpoints.apps.messages.providers.mattermost.send import send_mattermost
# from server.api.endpoints.apps.messages.providers.slack.send import send_slack


async def send(
    message: str,
    ai_mate_username: str,
    target: dict,
    attachments: List[dict] = []
) -> MessagesSendOutput:
    """
    Send a message to a target provider
    """
    target_dict = target if isinstance(target, dict) else target.__dict__
    attachments_dict = [
        attachment if isinstance(attachment, dict) else attachment.__dict__
        for attachment in attachments
    ] if attachments else []

    input = MessagesSendInput(
        message=message,
        ai_mate_username=ai_mate_username,
        target=Target(
            team=target_dict.get("team"),
            channel_name=target_dict.get("channel_name"),
            channel_id=target_dict.get("channel_id"),
            thread_id=target_dict.get("thread_id")
        ),
        attachments=[Attachment(
            filename=attachment.get("filename"),
            base64_content=attachment.get("base64_content")
        ) for attachment in attachments_dict] if attachments_dict else []
    )

    if input.target.provider == "Discord":
        return await send_discord(
            message=message,
            ai_mate_username=ai_mate_username,
            target=target,
            attachments=attachments
        )
    # elif input.target.provider == "Mattermost":
    #     return await send_mattermost(input)
    # elif input.target.provider == "Slack":
    #     return await send_slack(input)