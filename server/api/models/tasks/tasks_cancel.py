
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

from pydantic import BaseModel, Field

class TasksCancelOutput(BaseModel):
    status: str = Field("successfully cancelled", description="Status of the cancellation request")


tasks_cancel_output_example = {
    "status": "successfully cancelled"
}