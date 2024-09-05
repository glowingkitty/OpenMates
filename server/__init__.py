import traceback
import sys
import os
import re
import inspect

# Fix import path
full_current_init_path = os.path.realpath(__file__)
main_directory_for_init = re.sub('skills.*', '', full_current_init_path)
sys.path.append(main_directory_for_init)

from server.logging.add_to_log import add_to_log