from discord.ext import commands
import asyncio
import logging
import yaml
import os
import sys
from discord import Intents, File, DMChannel  # Import the Intents and File classes
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define a function to start a bot instance
async def start_bot(token: str, name: str):
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

    @bot.event
    async def on_ready():
        # Log when the bot is connected
        logger.info(f'Bot {name} is connected as {bot.user}')

    @bot.event
    async def on_message(message):
        # Ignore messages from the bot itself
        if message.author == bot.user:
            return

        # Check if the message is a DM
        if isinstance(message.channel, DMChannel):
            # Process direct messages
            logger.info(f"Received DM from {message.author}: {message.content}")
            await message.channel.send("Thanks for your DM!")

        # Check if the bot is mentioned in the message
        elif bot.user in message.mentions:
            guild = message.guild
            if guild:
                # Log the message received from a user mentioning the bot
                logger.info(f'Message mentioning {name} from {guild.name}: {message.content}')

                if message.attachments:
                    for attachment in message.attachments:
                        logger.info(f"Attachment: {attachment.filename}")

            # Example response to the user
            await message.channel.send(f"You mentioned {name}!")

    @bot.event
    async def on_message_edit(before, after):
        # Check if the bot is mentioned in the edited message
        if bot.user in after.mentions:
            guild = after.guild
            if guild:
                # Log the edited message mentioning the bot
                logger.info(f'Edited message mentioning {name} from {guild.name}: {after.content}')

                if after.attachments:
                    for attachment in after.attachments:
                        logger.info(f"Attachment in edited message: {attachment.filename}")

            # Example response to the user
            await after.channel.send(f"You mentioned {name} in an edited message!")

    @bot.event
    async def on_guild_join(guild):
        # Log the event of joining a new guild
        logger.info(f"Bot has joined the guild: {guild.name}")

        # Send a hello message to the system channel if available
        if guild.system_channel:
            await guild.system_channel.send("Hello! I'm your new bot. Thanks for inviting me!")

    # Run the bot using its token
    await bot.start(token)


# Main function to start all bots concurrently
async def main():
    # Load configuration
    with open("server.yml", 'r') as file:
        config = yaml.safe_load(file)

    # Check if the Discord provider is active
    discord_config = config['settings']['apps']['messages']['providers']['discord']
    if discord_config['active']:
        # Extract bot configurations and replace placeholders with actual tokens
        bots = discord_config['bots']
        active_bots = [
            {
                'name': bot_name,
                'token': os.getenv(bot_info['token'].strip('${}'))  # Get the token from environment variables
            }
            for bot_name, bot_info in bots.items()
        ]
        # remove bots with no token
        active_bots = [bot for bot in active_bots if bot['token']]

        # Log the number of active bots
        logger.info(f"Starting {len(active_bots)} active Discord bots.")

        # Run all active bots concurrently
        await asyncio.gather(
            *[start_bot(token=bot['token'], name=bot['name']) for bot in active_bots]
        )
    else:
        logger.info("Discord provider is not active. Exiting...")
        sys.exit(0)

# Run the main function using asyncio
asyncio.run(main())