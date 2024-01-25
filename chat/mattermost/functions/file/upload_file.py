import base64
import requests
import traceback
import sys
import os
import re
import io

# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)

from chat.mattermost.functions.user.get_user_access_token import get_user_access_token
from server.setup.load_secrets import load_secrets
from server.error.process_error import process_error
from server.queue.write_message_to_outgoing_messages import write_message_to_outgoing_messages


# https://api.mattermost.com/#tag/files/operation/UploadFile

def upload_file(channel_id: str, file_attachment: dict, attach_to_message: dict = None) -> str:
    print("uploading file:"+file_attachment['name']+" to channel: "+channel_id)
    try:
        secrets = load_secrets()

        # load user access token and domain from environment variables
        user_access_token = get_user_access_token()
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]
        url = f"{mattermost_domain}/api/v4/files"
        headers = {'Authorization': f'Bearer {user_access_token}'}
        data = {'channel_id': channel_id}
        files = {'files': open(file_attachment['file_path'], 'rb')}
        
        response = requests.post(url, headers=headers, data=data, files=files)
        if response.status_code == 201:
            file_id = response.json()['file_infos'][0]['id']
            print("file uploaded with ID: " + file_id)

            # delete file from file_path
            os.remove(file_attachment['file_path'])

        else:
            raise Exception(f"Failed to upload file: {response.text}")


        if attach_to_message:
            # attach file to message and send it
            message_content = attach_to_message['message_content']
            message_bot_sender = attach_to_message['message_bot_sender']
            message_channel_id = attach_to_message['message_channel_id']
            message_thread_id = attach_to_message['message_thread_id']

            # send the file to the thread
            write_message_to_outgoing_messages(
                full_message=message_content,
                channel_id=message_channel_id,
                thread_id=message_thread_id,
                bot_name=message_bot_sender,
                file_ids=[file_id]
            )

        return file_id
    
    except Exception:
        process_error("Failed uploading a file", traceback=traceback.format_exc())
        return None