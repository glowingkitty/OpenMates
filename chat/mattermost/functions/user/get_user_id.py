import requests
import traceback
import os
import re
import sys

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from server import *

from server.setup.load_secrets import load_secrets
from chat.mattermost.functions.user.get_user_access_token import get_user_access_token

user_ids = {}


def get_user_id(username: str) -> str:
    try:
        add_to_log(state="start", module_name="Mattermost", color="blue")

        if username in user_ids:
            return user_ids[username]

        secrets = load_secrets()
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]

        url = f"{mattermost_domain}/api/v4/users/username/{username}"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            # handle "id"="api.context.session_expired.app_error"
            if response.status_code == 401:
                add_to_log(state="error", message=f"User access token is invalid. You need to request a new one. Use get_user_access_token.py.")
                shutdown("token_invalid")

            raise Exception(f"Failed to get user id for {username}: {response.text}")
        user_id = response.json()["id"]
        user_ids[username] = user_id

        add_to_log(state="success", message=f"Successfully retrieved user ID for '{username}'")
        return user_id
    
    except Exception:
        process_error(f"Failed to get user ID for '{username}'", traceback=traceback.format_exc())
        return None


if __name__ == "__main__":
    get_user_id("sophia")