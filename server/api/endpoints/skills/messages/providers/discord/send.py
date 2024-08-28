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
from typing import List, Union, Any
from fastapi import HTTPException

async def send(
    message: str,
    ai_mate_username: str,
    target: Union[dict, Any],
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

    # Convert target to dict if it's not already
    target_dict = target if isinstance(target, dict) else target.__dict__
    attachments_dict = [
        attachment if isinstance(attachment, dict) else attachment.__dict__
        for attachment in attachments
    ] if attachments else []

    intents = discord.Intents.default()
    intents.guilds = True
    intents.guild_messages = True
    client = discord.Client(intents=intents)
    result = None

    @client.event
    async def on_ready():
        nonlocal result
        try:
            channel = None
            thread = None
            if target_dict.get('thread_id'):
                thread = await client.fetch_channel(int(target_dict['thread_id']))
                channel = thread
            elif target_dict.get('channel_id'):
                channel = client.get_channel(int(target_dict['channel_id']))
            elif target_dict.get('channel_name'):
                for guild in client.guilds:
                    channel = discord.utils.get(guild.channels, name=target_dict['channel_name'])
                    if channel:
                        break

            if not channel:
                raise ValueError(f"Channel or thread not found: {target_dict.get('thread_id') or target_dict.get('channel_id') or target_dict.get('channel_name')}")

            files = [
                File(io.BytesIO(base64.b64decode(attachment['base64_content'])), filename=attachment['filename'])
                for attachment in attachments_dict
            ] if attachments_dict else []

            response = await channel.send(content=message, files=files)

            result = MessagesSendOutput(
                message_id=str(response.id),
                channel_id=str(response.channel.id),
                thread_id=str(response.channel.id) if isinstance(response.channel, discord.Thread) else None
            )
        except Exception as e:
            add_to_log(f"Error: {str(e)}")
            add_to_log(f"Full error details: {traceback.format_exc()}")
            result = MessagesSendOutput(
                error=str(e),
            )
        finally:
            await client.close()

    await client.start(bot_token)
    return result