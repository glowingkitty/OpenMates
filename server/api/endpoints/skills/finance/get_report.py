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
from server.api.models.skills.finance.skills_finance_get_report import FinanceGetReportInput, FinanceGetReportOutput
from fastapi import HTTPException


async def get_report(
        report: Literal["profit_and_loss", "DE_jobcenter_EKS"],
        date_from: str,
        date_to: str,
        format: Literal["pdf", "xlsx","json"] = "pdf",
        include_attachments: bool = False
    ) -> FinanceGetReportOutput:
    """
    Get a report from Akaunting
    """
    try:
        input_data = FinanceGetReportInput(
            report=report,
            date_from=date_from,
            date_to=date_to,
            format=format,
            include_attachments=include_attachments
        )

        add_to_log(module_name="OpenMates | API | Finance | Get report", state="start", color="yellow", hide_variables=True)
        add_to_log("Getting a report from Finance ...")

        # TODO processing - what kind of reports? how to get them?



        report_response = {
            "report": input_data.report,
            "date_from": input_data.date_from,
            "date_to": input_data.date_to,
            "format": input_data.format
        }

        if input_data.include_attachments:
            report_response["include_attachments"] = input_data.include_attachments
            report_response["report_attachments_download_url"] = "/downloads/reports/a1b2c3d4e5/profit_and_loss_2023_attachments.zip"


        if input_data.format=="json":
            report_response["report_data"] = {
                "date": "2024-01-01",
                "amount": 1000
            }
        else:
            report_response["report_download_url"] = "/downloads/reports/a1b2c3d4e5/profit_and_loss_2023.pdf"

        if input_data.include_attachments or input_data.format!="json":
            report_response["downloads_expiration_datetime"] = "2023-06-15T14:30:00+00:00"

        return FinanceGetReportOutput(
            report_data=report_response
        )

    except HTTPException:
        raise

    except Exception:
        add_to_log(state="error", message=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get the report from Akaunting.")