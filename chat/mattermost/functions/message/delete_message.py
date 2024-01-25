import requests
import traceback
import sys
import os
import re

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from chat.mattermost.functions.user.get_user_name import get_user_name
from chat.mattermost.functions.user.get_user_access_token import get_user_access_token
from server import *


def delete_message(message_id: str):
    try:
        add_to_log(module_name="Mattermost", color="blue", state="start")
        add_to_log(f"Deleting message {message_id}...")

        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]

        url = f"{mattermost_domain}/api/v4/posts/{message_id}"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        response = requests.delete(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to delete message {message_id}: {response.text}")

    
    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error(f"Failed to delete message {message_id}.", traceback=traceback.format_exc())
        return None