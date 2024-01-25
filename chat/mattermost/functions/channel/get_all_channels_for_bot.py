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
from chat.mattermost.functions.user.get_user_id import get_user_id
from chat.mattermost.functions.user.get_user_access_token import get_user_access_token
from server.setup.load_secrets import load_secrets

channels_for_bot = {}

def get_all_channels_for_bot(bot_name="sophia",update_every_cycles=150):
    try:
        # check if botname in channels_for_bot
        # if channels_for_bot[bot_name]['update_cycle'] is older then 5 minutes (150 update cycles, every 2 sec), make update, else return it
        if bot_name in channels_for_bot:
            if channels_for_bot[bot_name]['update_cycle'] < update_every_cycles:
                channels_for_bot[bot_name]['update_cycle'] += 1
                return channels_for_bot[bot_name]['channels']


        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]
        team_name = secrets["MATTERMOST_TEAM_NAME"]

        team_id = get_team_id(team_name)
        user_id = get_user_id(bot_name)

        # get all channels for user
        url = f"{mattermost_domain}/api/v4/users/{user_id}/teams/{team_id}/channels"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to get all channels for user {bot_name}: {response.text}")
        
        response_json = response.json()
        channels = []
        for channel in response_json:
            channels.append({
                "id": channel["id"],
                "name": channel["display_name"] if channel["display_name"]!="" else channel["name"],
                "type": channel["type"],
            })

        # add the channels to the dict
        channels_for_bot[bot_name] = {
            "channels": channels,
            "update_cycle": 0
        }

        return channels
    
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None