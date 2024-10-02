import logging
import os
import tempfile

from ebooklib import epub
from fastapi import (
    APIRouter, Depends, FastAPI, File, Form, HTTPException, Path, Query, Request, UploadFile, WebSocket
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.responses import FileResponse
from starlette.status import HTTP_429_TOO_MANY_REQUESTS
from typing import List, Literal, Optional, Union
import uvicorn

# Import models
from server.api.models.billing.billing_get_balance import (
    BillingBalanceOutput, BillingGetBalanceInput
)
from server.api.models.mates.mates_ask import (
    MatesAskInput
)
from server.api.models.mates.mates_create import (
    MatesCreateInput
)
from server.api.models.mates.mates_delete import mates_delete_output_example
from server.api.models.mates.mates_get_all import mates_get_all_output_example
from server.api.models.mates.mates_get_one import mates_get_one_output_example
from server.api.models.mates.mates_update import (
    MatesUpdateInput
)
from server.api.models.skills.ai.skills_ai_ask import (
    AiAskInput, AiAskOutput, AiAskOutputStream
)
from server.api.models.skills.ai.skills_ai_estimate_cost import (
    AiEstimateCostInput, AiEstimateCostOutput
)
from server.api.models.skills.code.skills_code_plan import (
    CodePlanInput, CodePlanOutput
)
from server.api.models.skills.code.skills_code_write import (
    CodeWriteInput, CodeWriteOutput
)
from server.api.models.skills.docs.skills_docs_create import (
    DocsCreateInput
)
from server.api.models.skills.finance.skills_finance_get_report import (
    FinanceGetReportInput, FinanceGetReportOutput
)
from server.api.models.skills.finance.skills_finance_get_transactions import (
    FinanceGetTransactionsInput, FinanceGetTransactionsOutput
)
from server.api.models.skills.files.skills_files_delete import (
    FilesDeleteOutput
)
from server.api.models.skills.files.skills_files_upload import (
    FilesUploadOutput
)
from server.api.models.skills.messages.skills_connect_server import (
    MessagesConnectInput, MessagesConnectOutput
)
from server.api.models.skills.messages.skills_send_message import (
    MessagesSendInput, MessagesSendOutput
)
from server.api.models.skills.photos.skills_photos_resize_image import photos_resize_output_example
from server.api.models.skills.skills_get_one import skills_get_one_output_example
from server.api.models.skills.videos.skills_videos_get_transcript import (
    VideosGetTranscriptInput, VideosGetTranscriptOutput
)
from server.api.models.skills.web.skills_web_read import (
    WebReadInput, WebReadOutput
)
from server.api.models.skills.web.skills_web_view import (
    WebViewInput, WebViewOutput
)
from server.api.models.skills.business.skills_business_create_pitch import (
    BusinessCreatePitchInput, BusinessCreatePitchOutput
)
from server.api.models.skills.business.skills_business_create_application import (
    BusinessCreateApplicationInput, BusinessCreateApplicationOutput
)
from server.api.models.skills.business.skills_business_plan_application import (
    BusinessPlanApplicationInput, BusinessPlanApplicationOutput
)
from server.api.models.tasks.tasks_cancel import (
    TasksCancelOutput
)
from server.api.models.tasks.tasks_create import (
    Task
)
from server.api.models.tasks.tasks_get_task import tasks_get_task_output_example
from server.api.models.teams.teams_get_all import teams_get_all_output_example
from server.api.models.teams.teams_get_one import teams_get_one_output_example
from server.api.models.users.users_create import (
    UsersCreateInput, UsersCreateOutput
)
from server.api.models.users.users_create_new_api_token import (
    UsersCreateNewApiTokenInput
)
from server.api.models.users.users_get_all import users_get_all_output_example
from server.api.models.users.users_get_one import User, users_get_one_output_example
from server.api.models.users.users_replace_profile_picture import users_replace_profile_picture_output_example

# Import endpoints
from server.api.endpoints.billing.get_balance import get_balance as billing_get_balance_processing
from server.api.endpoints.mates.ask_mate import ask_mate as ask_mate_processing
from server.api.endpoints.mates.call_mate import call_mate as call_mate_processing
from server.api.endpoints.mates.create_mate import create_mate as create_mate_processing
from server.api.endpoints.mates.delete_mate import delete_mate as delete_mate_processing
from server.api.endpoints.mates.get_mate import get_mate as get_mate_processing
from server.api.endpoints.mates.get_mates import get_mates as get_mates_processing
from server.api.endpoints.mates.update_mate import update_mate as update_mate_processing
from server.api.endpoints.skills.ai.ask import ask as skill_ai_ask_processing
from server.api.endpoints.skills.ai.estimate_cost import estimate_cost as skill_ai_estimate_cost_processing
from server.api.endpoints.skills.code.plan import plan as skill_code_plan_processing
from server.api.endpoints.skills.code.write import write as skill_code_write_processing
from server.api.endpoints.skills.docs.create import create as skill_docs_create_processing
from server.api.endpoints.skills.files.delete import delete as skill_files_delete_processing
from server.api.endpoints.skills.files.download import download as skill_files_download_processing
from server.api.endpoints.skills.files.upload import upload as skill_files_upload_processing
from server.api.endpoints.skills.finance.get_report import get_report as skill_finance_get_report_processing
from server.api.endpoints.skills.finance.get_transactions import get_transactions as skill_finance_get_transactions_processing
from server.api.endpoints.skills.get_skill import get_skill as get_skill_processing
from server.api.endpoints.skills.messages.connect import connect as skill_messages_connect_processing
from server.api.endpoints.skills.messages.send import send as skill_messages_send_processing
from server.api.endpoints.skills.photos.resize_image import resize_image as skill_photos_resize_image_processing
from server.api.endpoints.skills.videos.get_transcript import get_transcript as skill_videos_get_transcript_processing
from server.api.endpoints.skills.web.read import read as skill_web_read_processing
from server.api.endpoints.skills.web.view import view as skill_web_view_processing
from server.api.endpoints.skills.business.create_pitch import create_pitch as skill_business_create_pitch_processing
from server.api.endpoints.skills.business.plan_application import plan_application as skill_business_plan_application_processing
from server.api.endpoints.skills.business.create_application import create_application as skill_business_create_application_processing
from server.api.endpoints.tasks.cancel import cancel as tasks_cancel_processing
from server.api.endpoints.tasks.create import create as tasks_create_processing
from server.api.endpoints.tasks.get_task import get as tasks_get_task_processing
from server.api.endpoints.teams.get_team import get_team as get_team_processing
from server.api.endpoints.teams.get_teams import get_teams as get_teams_processing
from server.api.endpoints.users.create_new_api_token import create_new_api_token as create_new_api_token_processing
from server.api.endpoints.users.create_user import create_user as create_user_processing
from server.api.endpoints.users.get_user import get_user as get_user_processing
from server.api.endpoints.users.get_users import get_users as get_users_processing
from server.api.endpoints.users.replace_profile_picture import replace_profile_picture as replace_profile_picture_processing

# Import security and validation
from server.api.security.validation.validate_invite_code import validate_invite_code
from server.api.security.validation.validate_permissions import validate_permissions

# Import parameters and metadata
from server.api.docs.parameters import (
    billing_endpoints, input_parameter_descriptions, mates_endpoints, server_endpoints, skills_ai_endpoints,
    skills_books_endpoints, skills_code_endpoints, skills_docs_endpoints, skills_endpoints, skills_files_endpoints,
    skills_finance_endpoints, skills_messages_endpoints, skills_photos_endpoints, skills_videos_endpoints, skills_web_endpoints,
    skills_business_endpoints, tasks_endpoints, teams_endpoints, users_endpoints
)

# Import Celery tasks
from server.api.endpoints.tasks.tasks import ask_mate_task, book_translate_task

# Import startup and shutdown functions
from server.api.startup import api_startup
from server.api.shutdown import api_shutdown