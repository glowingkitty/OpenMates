################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('chat.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from chat.mattermost.functions.channel.get_all_channels import get_all_channels
from chat.mattermost.functions.message.get_all_messages_for_channel import get_all_messages_for_channel
from chat.mattermost.functions.message.delete_message import delete_message
import time


def delete_all_old_messages(max_age_days: int = 30):
    try:
        add_to_log(module_name="Mattermost", color="blue", state="start")
        add_to_log("Deleting all old messages on server...")

        # Load user access token and domain from environment variables
        channels = get_all_channels()
        total_message_count = 0
        all_message_to_be_deleted = []
        
        # for every channel, get all messages
        for channel in channels:
            messages = get_all_messages_for_channel(channel["id"], get_all=True)
            total_message_count += len(messages)
            # for every message, check if "create_at" unix timestamp is older than max_age_days
            for message in messages:
                if message["create_at"] < (time.time() - (max_age_days * 24 * 60 * 60)):
                    all_message_to_be_deleted.append(message)
        
        add_to_log(f"Found {len(all_message_to_be_deleted)} messages to be deleted (out of {total_message_count} messages in total).")
        add_to_log("Are you sure you want to delete all these messages? (y/n)")
        user_input = input()
        if user_input != "y":
            add_to_log("Aborting ...")
            return False

        for message in all_message_to_be_deleted:
            # first delete all message attachments
            # TODO mattermost API does not support deleting files (seriously?). Need to find another way another time.
            # if message["attached_files"]:
            #     for file in message["attached_files"]:
            #         delete_file(file["id"])
            #         time.sleep(0.2)
            delete_message(message["id"])
            time.sleep(0.2)

        add_to_log(f"Successfully deleted all old messages on server", state="success")
        return True

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to delete all old messages", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    delete_all_old_messages()