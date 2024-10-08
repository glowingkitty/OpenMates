from discord.ext import commands
import asyncio
import logging
import yaml
import os
import sys
# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define a function to start a bot instance
async def start_bot(bot_config):
    # Extract token, name, and description from the bot configuration
    token = bot_config['messenger_bots']['discord']['token']
    name = bot_config['name']
    description = bot_config['description']

    # Log the bot's name and description
    logger.info(f'Starting bot: {name} - {description}')

    bot = commands.Bot(command_prefix=commands.when_mentioned)  # Use when_mentioned to handle @botusername

    @bot.event
    async def on_ready():
        # Log when the bot is connected
        logger.info(f'Bot {name} is connected as {bot.user}')

    @bot.event
    async def on_message(message):
        # Ignore messages from the bot itself
        if message.author == bot.user:
            return

        # Check if the bot is mentioned in the message
        if bot.user in message.mentions:
            guild = message.guild
            if guild:
                # Log the message received from a user mentioning the bot
                logger.info(f'Message mentioning {name} from {guild.name}: {message.content}')

            # Example response to the user
            await message.channel.send(f"You mentioned {name}!")

    # Run the bot using its token
    await bot.start(token)

# Load bot configuration from a YAML file
def load_config():
    # Get the current script directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Split the path at 'server' and construct the new path
    base_path = current_dir.split('server')[0] + 'server/server/server.yml'

    # Log the path being used for the configuration file
    logger.debug(f"Loading configuration from: {base_path}")

    with open(base_path, 'r') as file:
        config = yaml.safe_load(file)
    return config

# Main function to start all bots concurrently
async def main():
    # Load configuration
    config = load_config()

    # Check if the Discord provider is active
    discord_config = config['settings']['apps']['messages']['providers']['discord']
    if discord_config['active']:
        # Extract bot configurations
        bots = discord_config['bots']
        active_bots = [
            {'name': bot_name, 'token': bot_info['token'], 'description': config['settings']['mates'][bot_name]['description']}
            for bot_name, bot_info in bots.items()
        ]

        # Log the number of active bots
        logger.info(f"Starting {len(active_bots)} active Discord bots.")

        # Run all active bots concurrently
        await asyncio.gather(
            *[start_bot(bot) for bot in active_bots]
        )
    else:
        logger.info("Discord provider is not active. Exiting...")
        sys.exit(0)

# Run the main function using asyncio
asyncio.run(main())