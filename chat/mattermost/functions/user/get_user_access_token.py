import requests
import traceback
import os
import re
import sys

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from server.setup.load_secrets import load_secrets
from server.setup.save_secrets import save_secrets

def get_user_access_token(restart_auth_flow: bool = False):
    try:
        secrets = load_secrets()

        # test if secrets["MATTERMOST_ACCESS_TOKEN_USER"] has already been set
        if not restart_auth_flow and secrets["MATTERMOST_ACCESS_TOKEN_USER"]!="":
            return secrets["MATTERMOST_ACCESS_TOKEN_USER"]
        
        username = input("Enter your email: ")
        password = input("Enter your password: ")

        url = f"{secrets['MATTERMOST_DOMAIN']}/api/v4/users/login"
        data = {"login_id": username, "password": password}
        response = requests.post(url, json=data)
        if response.status_code == 200:
            secrets["MATTERMOST_ACCESS_TOKEN_USER"] = response.headers["Token"]
        elif response.json()["id"] == "mfa.validate_token.authenticate.app_error":
            mfa_token = input("Please enter your MFA token: ")
            data["token"] = mfa_token
            response = requests.post(url, json=data)
            
            if response.status_code == 200:
                secrets["MATTERMOST_ACCESS_TOKEN_USER"] = response.headers["Token"]
            else:
                return None
        
        if secrets["MATTERMOST_ACCESS_TOKEN_USER"] != None:
            # save access token to .env file
            save_secrets(secrets)

            return secrets["MATTERMOST_ACCESS_TOKEN_USER"]

        else:
            return None
        
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None
    
if __name__ == "__main__":
    get_user_access_token(restart_auth_flow=True)