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

import discord
from discord import File
import base64
import io
from server.api.models.skills.messages.skills_send_message import MessagesSendOutput
from typing import List, Union
from fastapi import HTTPException

async def send(
    message: str,
    source: dict,
    target: dict,
    attachments: List[dict] = [],
    bot_token: str = os.environ.get('DISCORD_BOT_TOKEN')
) -> MessagesSendOutput:
    """
    Send a message to a Discord channel
    """
    add_to_log(module_name="OpenMates | API | Send message to Discord", state="start", color="yellow", hide_variables=True)
    add_to_log("Sending a message to a Discord channel ...")
    if not bot_token:
        raise ValueError("DISCORD_BOT_TOKEN is not set")

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    result = None

    @client.event
    async def on_ready():
        nonlocal result
        try:
            channel_id = target['channel_id'] if type(target) == dict else target.channel_id
            channel = client.get_channel(int(channel_id))
            if not channel:
                raise ValueError(f"Channel with ID {channel_id} not found")

            files = [
                File(io.BytesIO(base64.b64decode(attachment['base64_content'] if type(attachment) == dict else attachment.base64_content)), filename=attachment['filename'] if type(attachment) == dict else attachment.filename)
                for attachment in attachments
            ] if attachments else []

            response = await channel.send(content=message, files=files)

            add_to_log(response)

            result = MessagesSendOutput(
                message_id=str(response.id),
                channel_id=str(response.channel.id),
                thread_id=str(response.channel.id) if isinstance(response.channel, discord.Thread) else None
            )
        except Exception as e:
            add_to_log(f"Error: {str(e)}")
            add_to_log(f"Full error details: {traceback.format_exc()}")
            result = MessagesSendOutput()
        finally:
            await client.close()

    await client.start(bot_token)
    return result