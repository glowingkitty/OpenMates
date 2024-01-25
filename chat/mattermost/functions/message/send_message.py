import requests
import traceback
import sys
import os
import re
import json

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

from chat.mattermost.functions.channel.get_channel_id import get_channel_id

def send_message(
        message: str = "Hey there!", 
        bot_name: str = None,
        channel_name: str = None,
        channel_id: str = None,
        thread_id: str = None,
        file_ids: list = None) -> str:
    try:
        add_to_log(state="start", module_name="Mattermost", color="blue")
        
        secrets = load_secrets()

        # Load user access token and domain from environment variables
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]
        bot_token = secrets["MATTERMOST_ACCESS_TOKEN_" + bot_name.upper()]
        
        if not channel_id and channel_name:
            channel_id = get_channel_id(channel_name)

        # Send the message to channel
        headers = {
            'Authorization': 'Bearer ' + bot_token,
            'Content-Type': 'application/json'
        }

        url = f"{mattermost_domain}/api/v4/posts"
        data = {
            "file_ids": file_ids,
            "channel_id": channel_id,
            "message": message,
        }
        # If thread id is specified, send the message in the thread
        if thread_id:
            data["root_id"] = thread_id

        add_to_log(f"Sending message with data: {str(data)}")

        response = requests.post(url, headers=headers, data=json.dumps(data))
        if response.status_code != 201:
            raise Exception(f"Failed to send message to '{channel_name}': {response.text}.\n{data}")
        
        message_id = response.json()["id"]
        add_to_log(state="success", message=f"Message sent successfully: '{message_id}'(message_id)")
        return message_id
        
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to send message", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    send_message(
        message="test message", 
        channel_name="random",
        file_ids=["1ztgjrm9nbbefxz77ru5kp9uzo"]
    )