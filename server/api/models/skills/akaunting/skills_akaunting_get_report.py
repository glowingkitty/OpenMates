
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

from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


# POST /{team_slug}/skills/akaunting/get_report (get a report from Akaunting)

class AkauntingGetReportInput(BaseModel):
    """This is the model for the incoming parameters for POST /{team_slug}/skills/akaunting/get_report"""
    report_type: Literal["sales", "purchases", "custom"] = Field("sales", title="Report Type", description="The type of report to get")

    # prevent extra fields from being passed to API
    model_config = ConfigDict(extra="forbid")

# TODO update models and examples

akaunting_get_report_input_example = {
    "report_type": "sales",
}


class AkauntingGetReportOutput(BaseModel):
    """This is the model for the output of POST /{team_slug}/skills/akaunting/get_report"""
    report_data: dict = Field(..., description="The data from the report.")

akaunting_get_report_output_example = {
    "report_data": {
        "report_type": "sales",
        "report_data": {
            "date": "2024-01-01",
            "amount": 1000
        }
    }
}