import requests
import traceback
import sys
import os
import re

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from chat.mattermost.functions.team.get_team_id import get_team_id
from chat.mattermost.functions.user.get_user_access_token import get_user_access_token
from server.setup.load_secrets import load_secrets

channel_names = {}


def get_channel_name(channel_id:str, team_name: str="Glowingkitty"):
    try:
        if channel_id in channel_names:
            return channel_names[channel_id]
        
        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]

        team_id = get_team_id(team_name)

        # get the channel name based on the channel id
        url = f"{mattermost_domain}/api/v4/teams/{team_id}/channels/{channel_id}"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to get channel name for {channel_id}: {response.text}")
        channel_name = response.json()["name"]

        # add the channel name to the dict
        channel_names[channel_id] = channel_name

        return channel_name
    
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None