import os
import re
import sys
import time
import traceback

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *

from server.setup.save_secrets import save_secrets
from chat.mattermost.functions.user.get_user_id import get_user_id
from chat.mattermost.functions.user.create_bot import create_bot



def check_bots_exist_and_create_bots():
    try:
        add_to_log(state="start", module_name="Mattermost", color="blue")
        
        # Check if the bots exist, if not create them
        add_to_log("Checking if bots exist...")
        secrets = load_secrets()
        bots = load_bots()
        
        # for every bot, check if it exists
        for bot_name in bots["all_usernames"]:
            user_id = get_user_id(bot_name)
            time.sleep(0.2)
            if not user_id:
                add_to_log(f"Bot {bot_name} does not exist.")
                bot_access_token = create_bot(
                    username=bot_name,
                    display_name=bots[bot_name]["display_name"],
                    description=bots[bot_name]["description"],
                    upload_image=True,
                    return_access_token=True
                )

                # save bot access token to .env file
                secrets[f"MATTERMOST_ACCESS_TOKEN_{bot_name.upper()}"] = bot_access_token
                save_secrets(secrets)
                add_to_log(f"Bot {bot_name} created and access token updated.")
        
        add_to_log(state="success", message="All bots checked and created if necessary.")
        return True

    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to check or create bots", traceback=traceback.format_exc())
        return False

if __name__ == "__main__":
    check_bots_exist_and_create_bots()