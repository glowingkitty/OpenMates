import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server.logging.add_to_log import add_to_log
import inspect

def shutdown(reason: str = "KeyboardInterrupt"):
    # gracefully exit the program
    if reason == "KeyboardInterrupt":
        add_to_log(state="error",message="Pressed CTRL+C, exiting program...")
    sys.exit(0)