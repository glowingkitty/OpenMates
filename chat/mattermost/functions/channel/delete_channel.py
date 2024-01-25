import requests
import traceback
import sys
import os
import re

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from chat.mattermost.functions.user.get_user_access_token import get_user_access_token
from server.setup.load_secrets import load_secrets
from chat.mattermost.functions.channel.get_channel_id import get_channel_id


def delete_channel(channel_name):
    try:
        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]
        channel_id = get_channel_id(channel_name)

        # get the channel id based on the channel name
        url = f"{mattermost_domain}/api/v4/channels/{channel_id}"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        data ={
            "permanent": True
        }

        response = requests.delete(url, headers=headers, json=data)
        if response.status_code != 200:
            raise Exception(f"Failed to delete channel {channel_name}: {response.text}")

        return channel_id
        
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None