import hashlib
import time
import sys
import os
import re
import json
import uuid
import requests
from requests.models import Response
import collections
import inspect
import traceback


# fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
OpenMates_directory = re.sub('OpenMates.*', 'OpenMates', main_directory)
sys.path.append(main_directory)



errors = {}


def last_n_lines(file_name, N):
    # Open the file in read mode
    with open(file_name, 'r') as file:
        # Create a deque
        log_deque = collections.deque(file, N)
    return ''.join(list(log_deque))

def get_traceback(prev_frame):
    stack_summary = inspect.getouterframes(prev_frame)
    formatted_summary = [(frame[1], frame[2], frame[3], frame[4][0].strip()) if frame[4] else (frame[1], frame[2], frame[3], None) for frame in stack_summary]
    formatted_traceback = ''.join(traceback.format_list(formatted_summary))
    return formatted_traceback

def process_error(
        log_message: str = None,
        traceback: str = None,
        file_name: str = None,
        when_did_error_occure: str = None,
        file_path: str = None,
        local_variables: dict = None,
        global_variables: dict = None,
        delete_old_after_hours: int = 24) -> bool:
    
    from server.setup.load_secrets import load_secrets
    from server.setup.load_config import load_config
    from server.logging.add_to_log import add_to_log
    from chat.mattermost.functions.channel.get_channel_id import get_channel_id
    from server.setup.load_profile_details import load_profile_details

    profile_details = load_profile_details()

    # get data from the function that called this function
    frame = inspect.currentframe()
    file_path = file_path or frame.f_back.f_code.co_filename
    prev_frame = frame.f_back
    file_name = os.path.basename(prev_frame.f_code.co_filename)
    local_variables = {k: v for k, v in prev_frame.f_locals.items() if v is not None and k != 'self'}
    global_variables = {k: v for k, v in prev_frame.f_globals.items() if v is not None and k != 'self'}
    

    global errors

    secrets = load_secrets()
    config = load_config()


    # shorten traceback to the first 100 lines
    if traceback:
        traceback = "\n".join(traceback.split("\n")[:100])
    
    # also delete old errors (older than x seconds) from errors variable
    for error_short_code in list(errors.keys()):
        if int(time.time()) - errors[error_short_code]["first_occurrence_unix"] > delete_old_after_hours*60*60:
            print(f"Deleting old error from errors variable: {error_short_code}")
            del errors[error_short_code]

    # get hash of error_message
    error_message = f"@{profile_details['server_responsible_person']['chat_username']} 🚨 Sorry to interrupt you. Something went wrong. "
    if log_message:
        error_message += log_message
    error_message += " while processing the file ```" + file_name + "```.\n\n"
    if traceback:
        error_message += f"Here is the error message: \n\n```python\n{traceback}\n```"

    hash_object = hashlib.sha256(error_message.encode())
    error_short_code = hash_object.hexdigest()

    # check if error_short_code exists in errors variable
    if error_short_code in errors:
        # if it does, add "\n\nThis error repeats! It happened x times recently!" to the message
        error_message = error_message + f"\n\n### 🚨This error repeats itself! It happened {errors[error_short_code]['error_count']} times recently!"
        # add 1 to error count
        errors[error_short_code]["error_count"] += 1
    else:
        # if it doesn't, add it to errors variable
        errors[error_short_code] = {
            "error_count": 1,
            "first_occurrence_unix": int(time.time())
        }

    # send variables and file if in production
    if config and "environment" in config and config["environment"] == "production":

        all_variables = {
            "variables": {
                "global()": sanitize_dict(global_variables),
                "local()": sanitize_dict(local_variables)
            }
        }

        # save as json file with UUID as filename
        filename = str(uuid.uuid4())
        folder_path = f"{main_directory}temp_data/error/{filename}"
        file_path_json = f"{folder_path}/variables.json"
        # make sure the folder exists, if not, create it
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
        
        try:
            with open(file_path_json, "w") as f:
                json.dump(all_variables, f, indent=4)
        except Exception as e:
            print(f"Failed to save variables to json file")


        # send the error message to mattermost, with the all_variables .json and the .py file attached
        bot_token = secrets["MATTERMOST_ACCESS_TOKEN_SOPHIA"]
        mattermost_domain = secrets["MATTERMOST_DOMAIN"]
        team_name = secrets["MATTERMOST_TEAM_NAME"]
        uploadurl = f"{mattermost_domain}/api/v4/files"
        posturl = f"{mattermost_domain}/api/v4/posts"
        channel_id = get_channel_id(channel_name="server")
        headers = {'Authorization': f'Bearer {bot_token}'}


        file_ids = []

        # First, we upload the json with the variables
        try:
            data = {'channel_id': channel_id}
            files = {'files': open(file_path_json, 'rb')}
            
            response = requests.post(uploadurl, headers=headers, data=data, files=files)
            variable_json_file_id = response.json()['file_infos'][0]['id']
            file_ids.append(variable_json_file_id)

            # remove folder
            os.system(f"rm -rf {folder_path}")
        except:
            print(f"Failed to upload variables to mattermost.")

        
        # Then, we upload the last x lines of the log file ({OpenMates_directory}full_log.log)
        try:
            last_lines = last_n_lines(f"{OpenMates_directory}/logs/full_log.log", 100)
            files = {'before_error.log': last_lines}

            response = requests.post(uploadurl, headers=headers, data=data, files=files)
            log_file_id = response.json()['file_infos'][0]['id']
            file_ids.append(log_file_id)
        except:
            print(f"Failed to upload log file to mattermost.")


        # Then, we upload the .py file
        try:
            files = {'files': open(file_path, 'rb')}

            response = requests.post(uploadurl, headers=headers, data=data, files=files)
            py_file_id = response.json()['file_infos'][0]['id']
            file_ids.append(py_file_id)
        except:
            print(f"Failed to upload .py file to mattermost.")

        # Then, we create a post with the uploaded files
        headers.update({'Content-Type': 'application/json'})
        data = {
            "message": error_message,
            "channel_id": channel_id,
            "file_ids": file_ids
        }

        response = requests.post(posturl, headers=headers, data=json.dumps(data))

    # print a link to the error message
    if not log_message:
        log_message = when_did_error_occure
    
    add_to_log(file_name=file_name,state="error", message=log_message, frame=frame)
    if config and "environment" in config and config["environment"] == "production": 
        add_to_log(file_name=file_name,state="error", message=f"Error details: {mattermost_domain}/{team_name}/pl/{response.json()['id']}", frame=frame)
    add_to_log(file_name=file_name,state="error", message=traceback, frame=frame)
    del frame


def get_message_id_from_previous_error_message(error_short_code):
    # get message ID from error variable
    if error_short_code in errors:
        if "message_id" in errors[error_short_code]:
            return errors[error_short_code]["message_id"]

    return None
    

def add_message_id_to_error_details(error_short_code: str, message_id: str) -> bool:
    # add message ID to error variable
    if error_short_code in errors:
        errors[error_short_code]["message_id"] = message_id
        return True
    else:
        return False
    

def sanitize_dict(d):
    sensitive_keywords = [
        "key", "token", "accesstoken", "secret", "apikey",
        "password", "passwd", "pwd", "auth", "credential",
        "credentials", "private", "privkey", "access_key", "secret_key",
        "refresh_token", "jwt", "client_assertion", "auth_code"
    ]
    sensitive_keywords += [f"{keyword}_" for keyword in sensitive_keywords] + \
                          [f"_{keyword}" for keyword in sensitive_keywords]

    sanitized_dict = {}
    try:
        for key, value in d.items():
            if key.lower() == "secrets" and isinstance(value, dict):
                sanitized_dict[key] = {k: "****" + str(v)[-4:] if isinstance(v, str) else "****" for k, v in value.items()}
            elif isinstance(value, dict):
                sanitized_dict[key] = sanitize_dict(value)
            elif any(keyword in key.lower() for keyword in sensitive_keywords):
                sanitized_dict[key] = "****" + str(value)[-4:]
            elif isinstance(value, Response):
                sanitized_dict[key] = value.json()
            elif isinstance(value, bytes):
                sanitized_dict[key] = str(value)[:500]
            elif isinstance(value, str):
                sanitized_dict[key] = value
            elif isinstance(value, list):
                sanitized_dict[key] = value
            elif isinstance(value, int):
                sanitized_dict[key] = value
            elif isinstance(value, float):
                sanitized_dict[key] = value
            elif isinstance(value, bool):
                sanitized_dict[key] = value
            elif value == None:
                sanitized_dict[key] = value
            else:
                sanitized_dict[key] = str(value)[:500]
        return sanitized_dict
    except Exception as e:
        print(f"Error while sanitizing variables: {e}")
        return {}