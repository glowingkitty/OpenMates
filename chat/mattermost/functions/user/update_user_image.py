import requests
import os
import re
import sys
import traceback

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server.setup.load_secrets import load_secrets
from chat.mattermost.functions.user.get_user_access_token import get_user_access_token
from chat.mattermost.functions.user.get_user_id import get_user_id

def update_user_image(bot_name, image_path=None):
    try:
        # if no image path is provided, use the default image
        if not image_path:
            full_current_path = os.path.realpath(__file__)
            main_directory = re.sub('chat.*', '', full_current_path)
            image_path = main_directory + "server/profile_pictures/" + bot_name + ".jpeg"
            # check if the image exists
            if not os.path.exists(image_path):
                raise Exception(f"Image {image_path} does not exist.")
            
        # load image and convert to binary
        with open(image_path, 'rb') as f:
            image_data = f.read()

        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]

        # get user id
        user_id = get_user_id(bot_name)

        # upload image to mattermost
        url = f"{mattermost_domain}/api/v4/users/{user_id}/image"
        headers = {'Authorization': 'Bearer ' + user_access_token}
        files = {"image": image_data}
        response = requests.post(url, headers=headers, files=files)

        if response.status_code != 200:
            raise Exception(f"Failed to update user image: {response.text}")
        
    except Exception:
        error_log = traceback.format_exc()
        print(error_log)
        return None