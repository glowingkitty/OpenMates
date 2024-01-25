import requests
import os
import re
import sys

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *


def check_chat_server_online() -> bool:
    """
    Check if a Chat server is online and accessible.

    Returns:
        bool: True if the server is online and accessible, False otherwise.
    """
    try:
        add_to_log(state="start", module_name="Setup", color="orange")

        secrets = load_secrets()
        config = load_config()

        if config and "modules" in config and config["modules"]["chat_server"]["source"] == "Mattermost":
            server_domain = secrets["MATTERMOST_DOMAIN"]
            url = f"{server_domain}/api/v4/users/login"
            response = requests.post(url)
            if response.status_code == 400:
                add_to_log(state="success", message="Chat server is online and accessible.")
                return True
            add_to_log(state="fail", message="Chat server is not accessible.")
            return False
        else:
            add_to_log(state="fail", message="Error: Chat server type not supported.")
            return False

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to check if chat server is online", traceback=traceback.format_exc())
        return False

if __name__ == "__main__":
    check_chat_server_online()