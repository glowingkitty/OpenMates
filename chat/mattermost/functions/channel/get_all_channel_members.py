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
from chat.mattermost.functions.user.get_user_name import get_user_name

def get_all_channel_members(channel_name,with_usernames=True):
    try:
        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]
        channel_id = get_channel_id(channel_name)

        url = f"{mattermost_domain}/api/v4/channels/{channel_id}/members"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to get all channel members: {response.text}")
        members = response.json()

        # reduce the list to only the relevant information (id, name)
        members = [{
            "user_id": member["user_id"],
        } for member in members]

        # also get the usernames
        if with_usernames:
            members = [{
                "user_id": member["user_id"],
                "username": get_user_name(member["user_id"])
            } for member in members]

        return members
    
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None