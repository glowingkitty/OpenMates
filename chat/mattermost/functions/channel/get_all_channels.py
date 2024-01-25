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


def get_all_channels():
    try:
        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]

        # get the channel id based on the channel name
        url = f"{mattermost_domain}/api/v4/channels"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to get all channels: {response.text}")
        channels = response.json()

        # reduce the list to only the relevant information (id, name, type, display_name)
        channels = [{
            "id": channel["id"],
            "name": channel["name"],
            "display_name": channel["display_name"],
            "type": channel["type"]
        } for channel in channels]

        return channels
    
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None