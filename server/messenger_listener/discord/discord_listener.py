import discord
import asyncio
import os
import logging
import aiohttp
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Get environment variables
BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    logger.info(f'{client.user} has connected to Discord!')

@client.event
async def on_message(message):
    # Make sure the message is not from the bot itself
    if message.author == client.user:
        return

    message_data = {
        'content': message.content,
        'author': str(message.author),
        'channel': {
            "id": message.channel.id,
            "name": message.channel.name
        },
        'guild': {
            "id": message.guild.id,
            "name": message.guild.name
        }
    }

    # TODO search in redis for team with guild.id and get team_slug

    logger.info(f"Sending message to API: {message_data}")

    async with aiohttp.ClientSession() as session:
        try:
            team_slug = ""
            # TODO extract team_slug from message_data
            api_endpoint = f'http://rest-api:8000/v1/{team_slug}/skills/messages/process'
            logger.info(f"Sending message to API: {api_endpoint}")
            # async with session.post(api_endpoint, json=message_data) as response:
            #     if response.status == 200:
            #         logger.info(f"Successfully sent message to API: {message_data}")
            #     else:
            #         logger.error(f"Failed to send message to API. Status: {response.status}")
        except Exception as e:
            logger.error(f"Error sending message to API: {e}")

async def main():
    if not BOT_TOKEN:
        raise ValueError("DISCORD_BOT_TOKEN not found in environment variables")

    try:
        await client.start(BOT_TOKEN)
    except Exception as e:
        logger.error(f"An error occurred: {e}")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())