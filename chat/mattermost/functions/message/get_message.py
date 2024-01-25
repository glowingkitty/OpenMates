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


def get_message(message_id):
    try:
        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]

        # get all channels for user
        url = f"{mattermost_domain}/api/v4/posts/{message_id}"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to get messages: {response.text}")
        
        response_json = response.json()
        
        return response_json
    
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None