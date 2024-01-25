import requests
import traceback
import os
import re
import sys

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server.setup.load_secrets import load_secrets
from chat.mattermost.functions.user.get_user_access_token import get_user_access_token

team_ids = {}

def get_team_id(team_name):
    try:
        if team_name in team_ids:
            return team_ids[team_name]
        
        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]

        # send the GET request to get the team id
        url = f"{mattermost_domain}/api/v4/teams/name/{team_name}"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to get team id for {team_name}: {response.text}")
        team_id = response.json()["id"]

        # add the team id to the dict
        team_ids[team_name] = team_id

        return team_id
    
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None