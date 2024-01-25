import requests
import traceback
import os
import re
import sys
import time


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server.setup.load_secrets import load_secrets
from chat.mattermost.functions.user.get_user_access_token import get_user_access_token
from chat.mattermost.functions.user.update_user_image import update_user_image
from chat.mattermost.functions.user.get_bot_access_token import get_bot_access_token
from chat.mattermost.functions.team.add_user_to_team import add_user_to_team

def create_bot(
        username,
        display_name=None,
        description=None,
        upload_image=False,
        return_access_token=False):
    try:
        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]

        url = f"{mattermost_domain}/api/v4/bots"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        data = {
            "username": username
        }
        if display_name:
            data["display_name"] = display_name
        if description:
            data["description"] = description

        response = requests.post(url, headers=headers, json=data)
        if response.status_code != 201:
            if response.json()["id"] == "api.bot.create_disabled":
                raise Exception(f"Bot creation is disabled on the server. Please turn it on.")
            else:
                raise Exception(f"Failed to create bot {username}: {response.text}")
        print(f"Bot {username} created successfully.")
        user_id = response.json()["user_id"]

        # upload profile image
        if upload_image:
            time.sleep(0.2)
            # get path for the image based on bot name
            update_user_image(bot_name=username)

        # get the access token for the bot if requested
        if return_access_token:
            time.sleep(0.2)
            access_token = get_bot_access_token(username)
            return access_token
        
        # add to team
        time.sleep(0.2)
        add_user_to_team(user_name=username)

        return user_id
    
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None