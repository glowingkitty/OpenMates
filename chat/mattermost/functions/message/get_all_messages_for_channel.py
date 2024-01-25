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

def get_all_messages_for_channel(channel_id: str,messages_limit: int = 10,get_all: bool = False, messages_since_unix: int = None):
    try:
        add_to_log(module_name="Mattermost", color="blue", state="start")
        add_to_log(f"Getting all messages for channel {channel_id}...")

        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]

        # get all channels for user
        url = f"{mattermost_domain}/api/v4/channels/{channel_id}/posts"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }

        messages = []
        page = 0
        if get_all:
            per_page = 100
        else:
            per_page = min(100, messages_limit)

        while True:
            params = {"page": page, "per_page": per_page}
            response = requests.get(url, headers=headers, params=params)

            if response.status_code != 200:
                raise Exception(f"Failed to get all messages for channel {channel_id}: {response.text}")

            response_json = response.json()
            new_messages = response_json["posts"]

            # convert the dictionary to a list of dictionaries
            new_messages = [{
                "source": "Mattermost",
                "id": v["id"], 
                "message": v["message"],
                "create_at":int(v["create_at"]/1000) if v["create_at"] > 10000000000 else v["create_at"], # convert create_at from milliseconds to seconds
                "message_by_user_id":v["user_id"],
                "message_by_user_name":get_user_name(v["user_id"]),
                "channel_id":v["channel_id"],
                "reply_to_message_id":v["metadata"]["embeds"][0]["data"]["post_id"] if v["metadata"].get("embeds") and v["metadata"]["embeds"][0].get("data") and v["metadata"]["embeds"][0]["data"].get("post_id") else None,
                "root_id":v["root_id"],
                "attached_files":[{"id":x["id"], "name":x["name"], "type":x["mime_type"]} for x in v["metadata"]["files"]] if "files" in v["metadata"] else None
                } for k, v in new_messages.items()]

            messages.extend(new_messages)

            if not get_all:
                if len(new_messages) < per_page or len(messages) >= messages_limit:
                    break
            else:
                if len(new_messages) < per_page:
                    break

            page += 1

        # filter out messages that are older than the specified time
        if messages_since_unix:
            # convert create_at from milliseconds to seconds
            messages = [message for message in messages if message["create_at"] >= messages_since_unix]

        add_to_log(f"Successfully got all messages for channel {channel_id}. ({len(messages)})", state="success")
        return messages
    
    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error(f"Failed to get all messages for channel {channel_id}.", traceback=traceback.format_exc())
        return None
    

if __name__ == "__main__":
    # get all messages for channel
    channel_id = "x41sthisjjfzurnwzwm6kjubur"
    messages = get_all_messages_for_channel(channel_id,get_all=True)
    # save messages to json file
    import json
    with open("messages.json","w") as f:
        json.dump(messages,f,indent=4)