import requests
import traceback
import os
import re
import sys

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from server.setup.load_secrets import load_secrets
from server.setup.save_secrets import save_secrets
from chat.mattermost.functions.user.get_user_id import get_user_id
from chat.mattermost.functions.user.get_user_access_token import get_user_access_token

def get_bot_access_token(bot_name):
    try:
        secrets = load_secrets()

        bot_id = get_user_id(bot_name)
        user_access_token = get_user_access_token()
        url = f"{secrets['MATTERMOST_DOMAIN']}/api/v4/users/{bot_id}/tokens"
        data = {"description": "OpenMates"}
        headers = {'Authorization': 'Bearer ' + user_access_token}
        response = requests.post(url, headers=headers, json=data)
        if response.status_code != 200:
            raise Exception(f"Failed to get bot access token for bot: {response.text}")
        access_token = response.json()["token"]

        # save access token to .env file
        secrets["MATTERMOST_ACCESS_TOKEN_" + bot_name.upper()] = access_token
        save_secrets(secrets)

        return access_token


    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None