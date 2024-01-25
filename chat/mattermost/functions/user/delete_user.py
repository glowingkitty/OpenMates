import os
import re
import sys
import requests
from dotenv import load_dotenv
import traceback

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from chat.mattermost.functions.user.get_user_id import get_user_id
from chat.mattermost.functions.user.get_user_access_token import get_user_access_token
from server.setup.load_secrets import load_secrets


def delete_user(bot_name=None,bot_id=None):
    try:
        if not bot_name and not bot_id:
            raise Exception("Please provide either bot_name or bot_id")

        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]

        if not bot_id:
            bot_id = get_user_id(bot_name)

        url = f"{mattermost_domain}/api/v4/users/{bot_id}"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        data = {
            "permanent": True
        }
        response = requests.delete(url, headers=headers, json=data)
        if response.status_code != 200:
            raise Exception(f"Failed to delete bot {bot_name}: {response.text}")

        return True
    
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None