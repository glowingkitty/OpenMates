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
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://api:8000/message')  # Adjust the port if needed

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

async def send_to_api(message_data):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(API_ENDPOINT, json=message_data) as response:
                if response.status == 200:
                    logger.info(f"Successfully sent message to API: {message_data}")
                else:
                    logger.error(f"Failed to send message to API. Status: {response.status}")
        except Exception as e:
            logger.error(f"Error sending message to API: {e}")

@client.event
async def on_ready():
    logger.info(f'{client.user} has connected to Discord!')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    print(message)

    message_data = {
        'content': message.content,
        'author': str(message.author),
        'channel': str(message.channel),
        'guild': str(message.guild),
        'timestamp': message.created_at.isoformat()
    }

    logger.info(f"Received message: {message_data}")
    await send_to_api(message_data)

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