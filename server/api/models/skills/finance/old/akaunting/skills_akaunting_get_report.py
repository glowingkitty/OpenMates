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

from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator
from datetime import datetime, timedelta


# POST /{team_slug}/skills/akaunting/get_report (get a report from Akaunting)

class AkauntingGetReportInput(BaseModel):
    """This is the model for the incoming parameters for POST /{team_slug}/skills/akaunting/get_report"""
    report: Literal["profit_and_loss", "DE_jobcenter_EKS"] = Field(..., title="Report Type", description="The type of report to get")
    date_from: str = Field(..., title="Date From", description="The start date of the report (ISO 8601 format: YYYY-MM-DD)")
    date_to: str = Field(..., title="Date To", description="The end date of the report (ISO 8601 format: YYYY-MM-DD)")
    format: Literal["pdf", "xlsx", "json"] = Field("pdf", title="Format", description="The format of the report")
    include_attachments: bool = Field(False, title="Include Attachments", description="Include PDFs for invoices, bills, and bank transactions as proof")

    # prevent extra fields from being passed to API
    model_config = ConfigDict(extra="forbid")

    @field_validator('date_from', 'date_to')
    @classmethod
    def validate_date(cls, v):
        try:
            datetime.strptime(v, '%Y-%m-%d')
        except ValueError:
            raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {v}")
        return v

akaunting_get_report_input_example = {
    "report": "profit_and_loss",
    "date_from": "2023-01-01",
    "date_to": "2023-12-31",
    "format": "pdf",
    "include_attachments": True
}

class AkauntingGetReportOutput(AkauntingGetReportInput):
    """This is the model for the output of POST /{team_slug}/skills/akaunting/get_report"""
    report_data: Optional[dict] = Field(None, description="The data from the report (only for JSON format).")
    report_download_url: Optional[str] = Field(None, description="The URL to download the report (for PDF and XLSX formats).")
    report_attachments_download_url: Optional[str] = Field(None, description="The URL to download the attachments (if include_attachments is True).")
    downloads_expiration_datetime: Optional[str] = Field(None, description="The expiration datetime of the download URLs.")

    @field_validator('report_download_url')
    @classmethod
    def validate_download_url(cls, v):
        if v is not None:
            if not re.match(r'^/downloads/reports/[a-zA-Z0-9]+/[a-zA-Z0-9_-]+\.[a-zA-Z]+$', v):
                raise ValueError("Invalid download URL format. It should be /downloads/reports/{random_id}/{filename}")
        return v

    @field_validator('report_attachments_download_url')
    @classmethod
    def validate_attachments_download_url(cls, v):
        if v is not None:
            if not re.match(r'^/downloads/reports/[a-zA-Z0-9]+/[a-zA-Z0-9_-]+\.[a-zA-Z]+$', v):
                raise ValueError("Invalid attachments download URL format. It should be /downloads/reports/{random_id}/{filename}")
        return v

akaunting_get_report_output_example = {
    "report": "profit_and_loss",
    "date_from": "2023-01-01",
    "date_to": "2023-12-31",
    "format": "pdf",
    "include_attachments": True,
    "report_download_url": "/downloads/reports/a1b2c3d4e5/profit_and_loss_2023.pdf",
    "report_attachments_download_url": "/downloads/reports/a1b2c3d4e5/profit_and_loss_2023_attachments.zip",
    "downloads_expiration_datetime": "2024-01-15T14:30:00+00:00"
}