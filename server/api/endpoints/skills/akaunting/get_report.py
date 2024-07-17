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

from typing import List, Optional, Literal
from server.api.models.skills.akaunting.skills_akaunting_get_report import AkauntingGetReportOutput
from server.cms.strapi_requests import get_nested
from fastapi.responses import JSONResponse
from fastapi import HTTPException


async def get_report(
        report_type: Literal["sales", "purchases", "custom"]
    ) -> AkauntingGetReportOutput:
    """
    Get a report from Akaunting
    """
    try:
        add_to_log(module_name="OpenMates | API | Akaunting | Get report", state="start", color="yellow", hide_variables=True)
        add_to_log("Getting a report from Akaunting ...")

        # TODO processing - what kind of reports? how to get them?

        return JSONResponse(status_code=200, content={"report_data": {"report_type": "sales", "report_data": {"date": "2024-01-01", "amount": 1000}}})

        # # return updated fields
        # if status_code == 200 and json_response["data"]:
        #     updated_response = {
        #         "id": get_nested(json_response, "id"),
        #         "username": get_nested(json_response, "username"),
        #         "updated_fields": updated_mate
        #     }
        #     return JSONResponse(status_code=200, content=updated_response)
        # else:
        #     raise HTTPException(status_code=500, detail="Failed to update the AI team mate.")

    except HTTPException:
        raise

    except Exception:
        process_error("Failed to get the report from Akaunting.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get the report from Akaunting.")