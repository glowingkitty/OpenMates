import requests
import traceback
import sys
import os
import re
import time

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from chat.mattermost.functions.channel.get_channel_id import get_channel_id
from chat.mattermost.functions.message.get_all_messages_for_channel import get_all_messages_for_channel
from server.setup.load_secrets import load_secrets
from chat.mattermost.functions.user.get_user_access_token import get_user_access_token


def delete_all_channel_messages(channel_name="server",channel_id=None):
    try:
        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]

        # get the channel id based on the channel name
        if not channel_id:
            channel_id = get_channel_id(channel_name)

        # get all messages from the channel
        messages = get_all_messages_for_channel(
            channel_id=channel_id, 
            messages_limit=None)

        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        for message in messages:
            try:
                url = f"{mattermost_domain}/api/v4/posts/{message['id']}"
                
                response = requests.delete(url, headers=headers)
                if response.status_code != 200:
                    raise Exception(f"Failed to delete message {message['id']}: {response.text}")
            except Exception:
                error_log = traceback.format_exc()
                print(error_log)
                continue

            time.sleep(0.5)


        return True
    
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None