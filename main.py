import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

from server.setup.check_chat_server import check_chat_server
from server.setup.start_all_bots import start_all_bots
import time

def main():
    try:
        add_to_log(state="start", module_name="OpenMates", color="yellow",
            input_variables={})
        
        add_to_log("Starting OpenMates...")
        time.sleep(5)
        server_running = check_chat_server()
        if server_running:
            start_all_bots()
        else:
            add_to_log(    state="error",
                message="Chat server not running, please start the Mattermost server, update the OpenMates .env file and try again."
            )
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("An error occurred in the main function", traceback=traceback.format_exc())

if __name__ == "__main__":
    main()