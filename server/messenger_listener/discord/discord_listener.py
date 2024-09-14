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

    # Make sure the bot was mentioned
    if client.user not in message.mentions:
        return

    logger.info("Bot was mentioned. Processing message...")

    # # Get the team slug from the API
    # async with aiohttp.ClientSession() as session:
    #     try:
    #         api_endpoint = 'http://rest-api:8000/v1/teamslug'
    #         logger.info(f"Getting team slug from API: {api_endpoint}")

    #         payload = {'discord_guild_id': message.guild.id}
    #         async with session.post(api_endpoint, json=payload) as response:
    #             if response.status == 200:
    #                 response = await response.json()
    #                 team_slug = response.get('team_slug')
    #                 logger.info(f"Team slug: {team_slug}")
    #             else:
    #                 logger.error(f"Failed to get team slug. Status: {response.status}")
    #                 # TODO send message to discord chat with url to login and connect team

    #     except Exception as e:
    #         logger.error(f"Error sending message to API: {e}")

    # # Send the message to the API
    # async with aiohttp.ClientSession() as session:
    #     try:
    #         api_endpoint = f'http://rest-api:8000/v1/{team_slug}/skills/messages/process'
    #         logger.info(f"Sending message to API: {api_endpoint}")

    #         message_data = {
    #             'content': message.content,
    #             'author': message.author.name,
    #             'channel_id': message.channel.id
    #         }
    #         # async with session.post(api_endpoint, json=message_data) as response:
    #         #     if response.status == 200:
    #         #         logger.info(f"Successfully sent message to API: {message_data}")
    #         #     else:
    #         #         logger.error(f"Failed to send message to API. Status: {response.status}")
    #     except Exception as e:
    #         logger.error(f"Error sending message to API: {e}")

@client.event
async def on_guild_join(guild):
    logger.info(f'Bot has joined a new guild: {guild.name} (ID: {guild.id})')

    # Check if the guild is registered in your software
    async with aiohttp.ClientSession() as session:
        try:
            api_endpoint = 'http://rest-api:8000/v1/teamslug'
            payload = {'discord_guild_id': guild.id}
            async with session.post(api_endpoint, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    team_slug = data.get('team_slug')
                    if not team_slug:
                        # Send a message to the server owner or a specific channel
                        owner = guild.owner
                        await owner.send(
                            "Your Discord guild is not connected to your OpenMates team."
                            "Visit the OpenMates website to connect your Discord guild to your team."
                        )
                        # Optionally, leave the guild
                        await guild.leave()
                        logger.info(f'Left guild: {guild.name} (ID: {guild.id}) because it is not registered.')
                    else:
                        logger.info(f'Guild {guild.name} (ID: {guild.id}) is registered with team slug: {team_slug}')
                else:
                    logger.error(f"Failed to get team slug. Status: {response.status}")
        except Exception as e:
            logger.error(f"Error checking guild registration: {e}")

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