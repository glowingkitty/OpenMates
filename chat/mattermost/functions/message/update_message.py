import sys
import os
import re
import requests

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from server.setup.load_secrets import load_secrets

def update_message(message_id, message="Hey there!", bot_name="sophia"):
    try:
        secrets = load_secrets()

        # load user access token and domain from environment variables
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]
        bot_token = secrets["MATTERMOST_ACCESS_TOKEN_" + bot_name.upper()]

        # update the message in the channel
        headers = {
            'Authorization': 'Bearer ' + bot_token,
            'Content-Type': 'application/json'
        }

        url = f"{mattermost_domain}/api/v4/posts/{message_id}"
        data = {
            "id": message_id,
            "message": message
        }
        response = requests.put(url, headers=headers, json=data)
        if response.status_code != 200:
            raise Exception(f"Failed to update message with id {message_id}: {response.text}")
        
        # return message_id
        return response.json()["id"]
        
        
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None