import requests
import sys
import os
import re

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from chat.mattermost.functions.user.get_user_access_token import get_user_access_token
from server.setup.load_secrets import load_secrets
from server.setup.load_bots import load_bots
from chat.mattermost.functions.team.get_team_id import get_team_id
from chat.mattermost.functions.user.get_user_name import get_user_name


def search_messages(bot_name="sophia",messages_since_unix=None):
    secrets = load_secrets()
    bots = load_bots(bot_username=bot_name)

    # load user access token and domain from environment variables
    user_access_token = get_user_access_token()
    mattermost_domain = secrets["MATTERMOST_DOMAIN"]
    team_name = secrets["MATTERMOST_TEAM_NAME"]
    team_id = get_team_id(team_name)

    url = f"{mattermost_domain}/api/v4/teams/{team_id}/posts/search"
    headers = {
        'Authorization': 'Bearer ' + user_access_token,
        'Content-Type': 'application/json'
    }

    # set up the search query to retrieve all new messages where the bot has been mentioned
    query = f'"@{bot_name}" is:unread'

    # send the search request to the Mattermost API
    response = requests.post(url, headers=headers, json={
        "terms": query,
        "is_or_search": True
        })
    response_json = response.json()

    # parse the response to retrieve the new messages
    new_messages = response_json["posts"]

    # convert the dictionary to a list of dictionaries, filtering for messages that mention the bot
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
        "attached_files":[{"id":x["id"], "name":x["name"], "type":x["mime_type"]} for x in v["metadata"]["files"]] if "files" in v["metadata"] else None,
        } for k, v in new_messages.items() if f"@{bot_name}" in v["message"]]
    
    # make sure to only include messages sent by a human (username is not a bot name)
    new_messages = [message for message in new_messages if message["message_by_user_name"] not in bots["all_usernames"]]
    
    # filter out messages that are older than the specified time
    if messages_since_unix:
        # convert create_at from milliseconds to seconds
        new_messages = [message for message in new_messages if message["create_at"] >= messages_since_unix]

    return new_messages


if __name__ == "__main__":
    messages = search_messages(bot_name="kitty")
    # write messages to file
    import json
    with open("messages.json", "w") as f:
        json.dump(messages, f, indent=4)