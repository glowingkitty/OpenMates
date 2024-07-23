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
from server.api.models.skills.akaunting.skills_akaunting_get_report import AkauntingGetReportOutput, AkauntingGetReportInput
from server.cms.strapi_requests import get_nested
from fastapi.responses import JSONResponse
from fastapi import HTTPException


async def get_report(
        report: Literal["profit_and_loss", "DE_jobcenter_EKS"],
        date_from: str,
        date_to: str,
        format: Literal["pdf", "xlsx","json"] = "pdf",
        include_attachments: bool = False
    ) -> AkauntingGetReportOutput:
    """
    Get a report from Akaunting
    """
    try:
        add_to_log(module_name="OpenMates | API | Akaunting | Get report", state="start", color="yellow", hide_variables=True)
        add_to_log("Getting a report from Akaunting ...")

        # TODO processing - what kind of reports? how to get them?



        report_response = {
            "report": report,
            "date_from": date_from,
            "date_to": date_to,
            "format": format
        }

        if include_attachments:
            report_response["include_attachments"] = include_attachments
            report_response["report_attachments_download_url"] = "/downloads/reports/a1b2c3d4e5/profit_and_loss_2023_attachments.zip"


        if format=="json":
            report_response["report_data"] = {
                "date": "2024-01-01",
                "amount": 1000
            }
        else:
            report_response["report_download_url"] = "/downloads/reports/a1b2c3d4e5/profit_and_loss_2023.pdf"

        if include_attachments or format!="json":
            report_response["downloads_expiration_datetime"] = "2023-06-15T14:30:00+00:00"

        return JSONResponse(status_code=200, content=report_response)

    except HTTPException:
        raise

    except Exception:
        process_error("Failed to get the report from Akaunting.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get the report from Akaunting.")