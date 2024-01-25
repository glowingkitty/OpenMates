################
# Default Imports
################
import sys
import os
import re
import traceback
import time

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

################

from server.setup.load_config import load_config
from skills.intelligence.load_systemprompt import load_systemprompt
from server.logging.add_to_log import add_to_log
from server.error.process_error import process_error
from server.shutdown.shutdown import shutdown
import inspect

bots = {"all_usernames": []}


def load_bots(bot_username:str = None) -> dict:
    global bots

    try:
        add_to_log(state="start", module_name="Bot", color="yellow")

        full_current_path = os.path.realpath(__file__)
        config_file_path = re.sub('OpenMates.*', 'OpenMates/my_profile/config.yaml', full_current_path)
        my_profile_folder_path = re.sub('OpenMates.*', 'OpenMates/my_profile', full_current_path)
        
        if not os.path.exists(config_file_path):
            raise FileNotFoundError(config_file_path + " not found")
        
        last_modified_time = os.path.getmtime(config_file_path)
        config_unchanged = "last_updated_timestamp" in bots and bots["last_updated_timestamp"] > last_modified_time
        my_profile_unchanged = True

        if "last_updated_timestamp" in bots:
            for root, dirs, files in os.walk(my_profile_folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_last_modified_time = os.path.getmtime(file_path)
                    if file_last_modified_time > bots["last_updated_timestamp"]:
                        my_profile_unchanged = False
                        break
                if not my_profile_unchanged:
                    break

        if config_unchanged and my_profile_unchanged:
            add_to_log(state="success", message="No updates found, using cached bots data.")
            return bots
        
        config = load_config()

        # if only one bot is requested, return only that bot
        for bot in config["active_bots"]:
            bot_name = bot["user_name"]
            if not bot_username or (bot_username and bot_username == bot_name):
                bots[bot_name] = {}
                bots[bot_name]["user_name"] = bot_name
                bots[bot_name]["description"] = bot["description"]
                bots[bot_name]["display_name"] = bot["display_name"]
                bots[bot_name]["model"] = bot["model"]
                bots[bot_name]["creativity"] = bot["creativity"] if "creativity" in bot else 0.5
                bots[bot_name]["voice"] = bot["voice"] if "voice" in bot else None
                bots[bot_name]["tools"] = bot["tools"] if "tools" in bot else None
                bots[bot_name]["system_prompt"] = load_systemprompt(
                    bot_user_name=bot_name,
                    bot_description=bot["description"],
                    bot_display_name=bot["display_name"],
                    bot_tools=bot["tools"] if "tools" in bot else None,
                    bot_product_details=bot["product_details"] if "product_details" in bot else None
                )

            bots["all_usernames"].append(bot_name)

        bots["last_updated_timestamp"] = int(time.time())
        add_to_log("Bots loaded and updated successfully.", state="success")

        return bots

    except KeyboardInterrupt:
        shutdown()

    except Exception as e:
        process_error("Failed to load bots", traceback=traceback.format_exc())
        return {}

if __name__ == "__main__":
    bots = load_bots()["grace"]
    print(bots)

    # try:
    #     while True:
    #         load_bots()
    #         time.sleep(3)
    # except KeyboardInterrupt:
    #     shutdown()