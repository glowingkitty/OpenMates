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
from server.setup.load_secrets import load_secrets


def get_all_messages_in_thread(thread_id, messages_limit=10):
    try:
        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]

        # get all channels for user
        url = f"{mattermost_domain}/api/v4/posts/{thread_id}/thread"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        response = requests.get(url, headers=headers,params={"page":0,"perPage":messages_limit,"direction":"up"})
        if response.status_code != 200:
            raise Exception(f"Failed to get all messages for thread {thread_id}: {response.text}")
        
        response_json = response.json()
        messages = response_json["posts"]
        
        # convert the dictionary to a list of dictionaries
        messages = [{
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
            } for k, v in messages.items()]
        
        return messages
    
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None