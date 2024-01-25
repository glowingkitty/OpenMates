import requests
import traceback
import sys
import os
import re

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from chat.mattermost.functions.user.get_user_access_token import get_user_access_token
from server import *


# https://api.mattermost.com/#tag/files/operation/GetFile

def get_file(file_id: str, file_name: str = None, save_file: bool = False) -> dict:
    try:
        add_to_log(module_name="Mattermost", color="blue", state="start")
        add_to_log("Getting file...")

        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]

        # get all channels for user
        url = f"{mattermost_domain}/api/v4/files/{file_id}"
        headers = {
            'Authorization': 'Bearer ' + user_access_token,
            'Content-Type': 'application/json'
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to get file: {response.text}")
        
        response_file = response.content

        # save the image file
        if save_file:
            if not os.path.exists(f"{main_directory}/temp_data/files"):
                os.makedirs(f"{main_directory}/temp_data/files")
                
            if not file_name:
                file_name = f"{file_id}.jpg"

            with open(f"{main_directory}/temp_data/files/{file_name}", 'wb') as f:
                f.write(response_file)
        
        add_to_log(f"Successfully got file", state="success")
        return response_file

    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"While getting a file", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    get_file(file_id="qiess3fqijbx3mys8dty887q4h",file_name="variables.json",save_file=True)