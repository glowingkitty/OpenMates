import requests
import traceback
import sys
import os
import re
from slugify import slugify

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from chat.mattermost.functions.team.get_team_id import get_team_id
from chat.mattermost.functions.user.get_user_access_token import get_user_access_token
from server.setup.load_secrets import load_secrets

channel_ids = {}


def get_channel_id(channel_name: str) -> str:
    try:
        channel_name = slugify(channel_name)
        if channel_name in channel_ids:
            return channel_ids[channel_name]
        
        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]

        team_id = get_team_id(secrets["MATTERMOST_TEAM_NAME"])

        # get the channel id based on the channel name
        url = f"{mattermost_domain}/api/v4/teams/{team_id}/channels/name/{channel_name}"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to get channel id for {channel_name}: {response.text}")
        channel_id = response.json()["id"]

        # add the channel id to the dict
        channel_ids[channel_name] = channel_id

        return channel_id
    
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None