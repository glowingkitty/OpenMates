################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from server.celery_app import app
from server.api.endpoints.mates.ask_mate import ask_mate as ask_mate_processing

# Celery tasks

@app.task
def ask_mate_task(team_slug, message, mate_username):
    return ask_mate_processing(team_slug, message, mate_username)