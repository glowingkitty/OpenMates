from discord.ext import commands
import asyncio
import logging
import yaml
import os
import sys
from discord import Intents, File, DMChannel  # Import the Intents and File classes
from dotenv import load_dotenv
import re  # Import the regular expression module
from server_config import get_server_config

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define a function to start a bot instance
async def start_bot(token: str, name: str, bot_ids: dict):
    # Log the bot's name and description
    logger.info(f'Starting bot: {name}')

    # Create an instance of Intents with default settings
    intents = Intents.default()
    # Enable the intents you need
    intents.messages = True  # To receive message events
    intents.guilds = True    # To receive guild events
    intents.dm_messages = True  # To receive direct message events

    # Create the bot instance with the specified intents
    bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)  # Use when_mentioned to handle @botusername

    def replace_ids_with_usernames(content):
        # Define a function to replace IDs with usernames
        def replace(match):
            user_id = match.group(1)
            # Get the username from bot_ids, capitalize it, or return the original ID if not found
            return bot_ids.get(user_id, f"<@{user_id}>").capitalize()

        # Use regex to find all user mentions and replace them
        return re.sub(r'<@(\d+)>', replace, content)

    @bot.event
    async def on_ready():
        # Log when the bot is connected
        logger.info(f'Bot {name} is connected as {bot.user}')

    @bot.event
    async def on_message(message):
        # Ignore messages from bots
        if message.author.bot:
            logger.debug(f"Ignoring message from bot: {message.author}")
            return

        # Check if the message is a DM
        if isinstance(message.channel, DMChannel):
            # Replace IDs with usernames in the message content
            message_content = replace_ids_with_usernames(message.content)

            # Process direct messages
            logger.debug(f"Received DM from {message.author}: {message_content}")
            await message.channel.send("Thanks for your DM!")

        # Check if the bot is mentioned in the message
        elif bot.user in message.mentions:
            # Replace IDs with usernames in the message content
            message_content = replace_ids_with_usernames(message.content)

            guild = message.guild
            if guild:
                # Log the message received from a user mentioning the bot
                logger.debug(f'Message mentioning {name} from {guild.name}: {message_content}')

                if message.attachments:
                    for attachment in message.attachments:
                        logger.debug(f"Attachment: {attachment.filename}")

            # Example response to the user
            await message.channel.send(f"You mentioned {name}!")

    @bot.event
    async def on_message_edit(before, after):
        # Ignore edits from bots
        if after.author.bot:
            logger.debug(f"Ignoring edit from bot: {after.author}")
            return

        # Check if the bot is mentioned in the edited message
        if bot.user in after.mentions:
            guild = after.guild
            if guild:
                # Replace IDs with usernames in the edited message content
                edited_message_content = replace_ids_with_usernames(after.content)

                # Log the edited message with replaced usernames
                logger.debug(f'Edited message mentioning {name} from {guild.name}: {edited_message_content}')

                if after.attachments:
                    for attachment in after.attachments:
                        logger.debug(f"Attachment in edited message: {attachment.filename}")

            # Example response to the user
            await after.channel.send(f"You mentioned {name} in an edited message!")

    @bot.event
    async def on_guild_join(guild):
        # Log the event of joining a new guild, including the bot's name
        logger.info(f"Bot {name} has joined the guild: {guild.name}")

        # Send a hello message to the system channel if available
        if guild.system_channel:
            await guild.system_channel.send("Hello! I'm your new bot. Thanks for inviting me!")

    # Run the bot using its token
    await bot.start(token)


# Main function to start all bots concurrently
async def main():
    # Check if the Discord provider is active
    discord_config = get_server_config('apps.messages.providers.discord')
    if discord_config.get('allowed', False):  # Changed 'active' to 'allowed'
        # Extract bot configurations and replace placeholders with actual tokens
        bots = discord_config['bots']
        active_bots = []
        bot_ids = {}

        for bot_name, bot_info in bots.items():
            token = os.getenv(bot_info['token'].strip('${}'))
            client_id = os.getenv(bot_info['client_id'].strip('${}'))

            if token and client_id:
                active_bots.append({
                    'name': bot_name,
                    'token': token,
                    'client_id': client_id
                })
                bot_ids[client_id] = bot_name

        # Log the number of active bots
        logger.info(f"Starting {len(active_bots)} active Discord bots.")
        logger.debug(f"Active bots: {', '.join([bot['name'] for bot in active_bots])}")

        # Run all active bots concurrently
        await asyncio.gather(
            *[start_bot(token=bot['token'], name=bot['name'], bot_ids=bot_ids) for bot in active_bots]
        )
    else:
        logger.info("Discord provider is not allowed. Exiting...")
        sys.exit(0)

# Run the main function using asyncio
if __name__ == "__main__":
    asyncio.run(main())