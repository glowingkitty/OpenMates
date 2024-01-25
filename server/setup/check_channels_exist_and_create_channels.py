import os
import re
import sys
import time
from slugify import slugify

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *

from chat.mattermost.functions.channel.create_channel import create_channel
from chat.mattermost.functions.channel.add_user_to_channel import add_user_to_channel
from chat.mattermost.functions.channel.get_all_channels import get_all_channels
from chat.mattermost.functions.channel.get_all_channel_members import get_all_channel_members


def check_channels_exist_and_create_channels():
    try:
        add_to_log(state="start", module_name="Mattermost", color="blue")
        
        add_to_log("Checking if channels exist...")

        config = load_config()
        channels = config["default_channels"]
        bots = config["invite_bots_to_channels"]

        # Get a list of all channels
        existing_channels = get_all_channels()

        # Create list of channels that still need to be created
        missing_channels = []
        for channel in channels:
            channel_slugified = slugify(channel)
            channel_exists = any(channel_slugified == existing_channel["name"] for existing_channel in existing_channels)
            if not channel_exists:
                add_to_log(f"Need to create channel: {channel}")
                missing_channels.append(channel)

        # Create missing channels
        for channel in missing_channels:
            create_channel(channel_name=channel)
            time.sleep(0.2)
            add_to_log(f"Channel created: {channel}")

        # For every channel, get list of all users
        for channel in channels:
            members = get_all_channel_members(channel_name=channel)
            for bot in bots:
                bot_in_channel = any(bot["user_name"] == member["username"] for member in members)
                if not bot_in_channel:
                    add_to_log(f"Adding bot to channel: {bot['user_name']}")
                    add_user_to_channel(user_name=bot["user_name"], channel_name=channel)
                    time.sleep(0.2)
                    add_to_log(f"Bot added to channel: {bot['user_name']} to {channel}")

        add_to_log(state="success", message="Finished checking and creating channels.")
        return True

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to check and create channels", traceback=traceback.format_exc())
        return False


if __name__ == "__main__":
    check_channels_exist_and_create_channels()