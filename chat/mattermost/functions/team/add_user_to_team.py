import traceback
import requests
import os
import re
import sys


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server.setup.load_secrets import load_secrets
from chat.mattermost.functions.user.get_user_access_token import get_user_access_token
from chat.mattermost.functions.team.get_team_id import get_team_id
from chat.mattermost.functions.user.get_user_id import get_user_id

def add_user_to_team(user_name):
    try:
        # add botname to team
        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]
        team_name = secrets["MATTERMOST_TEAM_NAME"]
        team_id = get_team_id(team_name)
        user_id = get_user_id(user_name)

        url = f"{mattermost_domain}/api/v4/teams/{team_id}/members"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        data = {
            "team_id": team_id,
            "user_id": user_id
        }
        response = requests.post(url, headers=headers, json=data)

        if response.status_code != 201:
            raise Exception(f"Failed to add user {user_name} to team {team_name}: {response.text}")
        
        return True

    except:
        error_log = traceback.format_exc()
        print(error_log)
        return None