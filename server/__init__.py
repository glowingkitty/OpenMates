import traceback
import sys
import os
import re
import inspect

# Fix import path
full_current_init_path = os.path.realpath(__file__)
main_directory_for_init = re.sub('skills.*', '', full_current_init_path)
sys.path.append(main_directory_for_init)

from server.setup.load_secrets import load_secrets
from server.setup.save_secrets import save_secrets
from server.setup.load_config import load_config
from server.setup.load_bots import load_bots
from server.setup.load_profile_details import load_profile_details
from server.error.process_error import process_error
from server.logging.add_to_log import add_to_log
from server.shutdown.shutdown import shutdown