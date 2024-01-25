import sys
import os
import re
import traceback

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *

from server.setup.check_chat_server_online import check_chat_server_online
from server.setup.check_bots_exist_and_create_bots import check_bots_exist_and_create_bots
from server.setup.check_channels_exist_and_create_channels import check_channels_exist_and_create_channels



def check_chat_server():
    try:
        add_to_log(state="start", module_name="Setup", color="orange")

        # Check if the chat server is running, all bots and channels exist
        # check if server is online
        add_to_log("Checking if chat server is online...")
        server_online = check_chat_server_online()
        if not server_online:
            add_to_log(state="error", message="Chat server is not online.")
            return False
        
        # check if bots exist
        add_to_log("Checking if bots exist and create them if not...")
        bots_exist = check_bots_exist_and_create_bots()
        if not bots_exist:
            add_to_log(state="error", message="Bots do not exist or could not be created.")
            return False
        
        # check if channels exist
        add_to_log("Checking if channels exist and create them if not...")
        channels_exist = check_channels_exist_and_create_channels()
        if not channels_exist:
            add_to_log(state="error", message="Channels do not exist or could not be created.")
            return False

        add_to_log(state="success", message="Chat server, bots, and channels are all set up correctly.")
        return True

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to check chat server setup", traceback=traceback.format_exc())
        return False

if __name__ == "__main__":
    check_chat_server()