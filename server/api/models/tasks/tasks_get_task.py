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

from server.api import *
################

tasks_get_task_output_example = {
    "id": "153e0027-e34d-27i7-9a9c-14a6375b1c97",
    "url": "/v1/openmatesdevs/tasks/153e0027-e34d-27i7-9a9c-14a6375b1c97",
    "api_endpoint": "/v1/openmatesdevs/skills/books/translate",
    "title": "Translate a book",
    "status": "success",
    "progress": 100,
    "time_started": "2023-05-17T12:34:56.789Z",
    "time_estimated_completion": "2023-05-17T12:36:00.000Z",
    "time_completion": "2023-05-17T12:36:01.030Z",
    "execution_time_seconds": 61.03,
    "total_cost_estimated": 720,
    "total_cost_real": 720,
    "output": {
        "name": "book_translated.epub",
        "url": "/v1/openmatesdevs/skills/files/books/book_translated.epub",
        "expiration_datetime": "2023-05-17T12:36:01.030Z",
        "access_public": False,
        "read_access_limited_to_teams": [],
        "read_access_limited_to_users": [],
        "write_access_limited_to_teams": [],
        "write_access_limited_to_users": []
    },
    "error": None
}