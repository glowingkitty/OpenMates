################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

import dropbox
from dropbox import DropboxOAuth2FlowNoRedirect




################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

import dropbox


def get_refresh_token(test_if_valid: bool = False) -> str:
    try:
        add_to_log(state="start", module_name="Cloud storage | Dropbox", color="blue")

        add_to_log(f"Getting refresh token from Dropbox ...")

        secrets = load_secrets()

        if secrets["DROPBOX_REFRESH_TOKEN"]:
            if test_if_valid:
                try:
                    with dropbox.Dropbox(oauth2_refresh_token=secrets["DROPBOX_REFRESH_TOKEN"], app_key=secrets["DROPBOX_APP_KEY"]) as dbx:
                        dbx.users_get_current_account()
                        add_to_log(state="success", message=f"Successfully tested refresh token")
                        return secrets["DROPBOX_REFRESH_TOKEN"]
                except dropbox.exceptions.AuthError:
                    add_to_log("Access token expired. Retrieving a new one ...")
            else:
                add_to_log(state="success", message=f"Successfully loaded refresh token from .env file")
                return secrets["DROPBOX_REFRESH_TOKEN"]
        
        auth_flow = DropboxOAuth2FlowNoRedirect(secrets["DROPBOX_APP_KEY"], use_pkce=True, token_access_type='offline')

        authorize_url = auth_flow.start()
        add_to_log("1. Go to: " + authorize_url)
        add_to_log("2. Click \"Allow\" (you might have to log in first).")
        add_to_log("3. Copy the authorization code.")
        add_to_log("Enter the authorization code: ")
        auth_code = input().strip()

        oauth_result = auth_flow.finish(auth_code)
        refresh_token = oauth_result.refresh_token

        with dropbox.Dropbox(oauth2_refresh_token=oauth_result.refresh_token, app_key=secrets["DROPBOX_APP_KEY"]) as dbx:
            dbx.users_get_current_account()
            secrets["DROPBOX_REFRESH_TOKEN"] = refresh_token
            add_to_log(state="success", message=f"Successfully generated refresh token for Dropbox.")
            save_secrets(secrets)


        return secrets["DROPBOX_REFRESH_TOKEN"]

    except Exception:
        process_error("Failed to get refresh token from Dropbox", traceback=traceback.format_exc())
        return None
    

if __name__ == "__main__":
    get_refresh_token(test_if_valid=True)