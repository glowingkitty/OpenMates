import requests
import traceback
import os
import re
import sys


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server.setup.load_secrets import load_secrets
from chat.mattermost.functions.user.get_user_access_token import get_user_access_token

user_names = {}

def get_user_name(user_id):
    try:
        if user_id in user_names:
            return user_names[user_id]
        
        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]

        # send the GET request to get the user name
        url = f"{mattermost_domain}/api/v4/users/ids"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        response = requests.post(url, headers=headers,json=[user_id])
        if response.status_code != 200:
            raise Exception(f"Failed to get user name for {user_id}: {response.text}")
        user_name = response.json()[0]["username"]

        # add the user name to the dict
        user_names[user_id] = user_name

        return user_name
    
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None