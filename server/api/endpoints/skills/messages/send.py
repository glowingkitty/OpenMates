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

from server.api.endpoints.skills.messages.providers.discord.send import send as send_discord
# from server.api.endpoints.skills.messages.providers.mattermost.send import send_mattermost
# from server.api.endpoints.skills.messages.providers.slack.send import send_slack


async def send(
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
            bot_name=source.get("bot_name") if type(source) == dict else source.bot_name,
            ai_mate_name=source.get("ai_mate_name") if type(source) == dict else source.ai_mate_name
        ),
        target=Target(
            provider=target.get("provider") if type(target) == dict else target.provider,
            group_id=target.get("group_id") if type(target) == dict else target.group_id,
            channel_name=target.get("channel_name") if type(target) == dict else target.channel_name,
            channel_id=target.get("channel_id") if type(target) == dict else target.channel_id,
            thread_id=target.get("thread_id") if type(target) == dict else target.thread_id
        ),
        attachments=[Attachment(
            filename=attachment.get("filename") if type(attachment) == dict else attachment.filename,
            base64_content=attachment.get("base64_content") if type(attachment) == dict else attachment.base64_content
        ) for attachment in attachments] if attachments else []
    )

    if input.target.provider == "Discord":
        return await send_discord(
            message=message,
            source=source,
            target=target,
            attachments=attachments
        )
    # elif input.target.provider == "Mattermost":
    #     return await send_mattermost(input)
    # elif input.target.provider == "Slack":
    #     return await send_slack(input)