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


def create_channel(
        channel_name,
        purpose=None,
        header=None,
        channel_type="P"):
    try:
        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]
        team_id = get_team_id(secrets["MATTERMOST_TEAM_NAME"])

        # get the channel id based on the channel name
        url = f"{mattermost_domain}/api/v4/channels"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        # make channel name domain compliant
        display_name = channel_name.capitalize()
        channel_name = slugify(channel_name)
        data = {
            "team_id": team_id,
            "name": channel_name,
            "display_name": display_name,
            "type": channel_type
        }
        if purpose:
            data["purpose"] = purpose
        if header:
            data["header"] = header

        response = requests.post(url, headers=headers, json=data)
        if response.status_code != 201:
            raise Exception(f"Failed to create channel {channel_name}: {response.text}")
        channel_id = response.json()["id"]
        print(f"Channel '{channel_name}' created successfully.")

        return channel_id
        
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None