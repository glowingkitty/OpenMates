import requests
import traceback
import sys
import os
import re

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from server.setup.load_secrets import load_secrets
from chat.mattermost.functions.channel.get_channel_id import get_channel_id
from chat.mattermost.functions.user.get_user_id import get_user_id


def send_typing_indicator(
        bot_name: str = None,
        channel_name: str = None,
        channel_id: str = None, 
        thread_id: str = None) -> bool:
    try:
        secrets = load_secrets()

        # load user access token and domain from environment variables
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]
        bot_token = secrets["MATTERMOST_ACCESS_TOKEN_" + bot_name.upper()]
        user_id = get_user_id(bot_name)

        if not channel_id and channel_name:
            channel_id = get_channel_id(channel_name)

        # send the message to channel
        headers = {
            'Authorization': 'Bearer ' + bot_token,
            'Content-Type': 'application/json'
        }

        url = f"{mattermost_domain}/api/v4/users/{user_id}/typing"
        data = {
            "channel_id": channel_id,
        }

        if thread_id:
            data["parent_id"] = thread_id

        response = requests.post(url, headers=headers, json=data)
        if response.status_code != 200:
            raise Exception(f"Failed to send typing indicator to {channel_name}: {response.text}")
        
        return True
        
        
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return False