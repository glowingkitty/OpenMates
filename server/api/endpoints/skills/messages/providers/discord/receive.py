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


import discord
from discord.ext import commands
import asyncio
import os
import re
import sys
from server import *
from fastapi import HTTPException
from server.api.models.skills.messages.skills_receive_message import MessagesReceiveOutput
from typing import List, Union, Any, Callable


class DiscordBot(commands.AutoShardedBot):
    def __init__(self, message_handler: Callable, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.message_handler = message_handler

    async def on_ready(self):
        add_to_log(f"Discord bot is ready for {self.user}")

    async def on_message(self, message):
        if message.author == self.user:
            return
        message_output = MessagesReceiveOutput(
            message=message.content,
            target=message.channel.name,
            attachments=message.attachments
        )
        await self.message_handler(**message_output.model_dump())

async def start_discord_listener(
    bot_token: str,
    message_handler: Callable
) -> None:
    """
    Start a Discord listener for a specific server
    """
    add_to_log(module_name="OpenMates | API | Start Discord Listener", state="start", color="yellow", hide_variables=True)

    intents = discord.Intents.default()
    intents.messages = True
    bot = DiscordBot(message_handler=message_handler, intents=intents, command_prefix="!")

    try:
        await bot.start(bot_token)
    except Exception as e:
        add_to_log(f"Error starting Discord bot: {str(e)}", color="red")