import logging
logger = logging.getLogger(__name__)

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

# Import security and validation
from server.api.security.validation.validate_invite_code import validate_invite_code
from server.api.security.validation.validate_permissions import validate_permissions

# Import startup and shutdown functions
from server.api.startup import api_startup
from server.api.shutdown import api_shutdown

##########################################################
# Mates
##########################################################
from server.api.endpoints.tasks.tasks import ask_mate_task
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
from server.api.endpoints.mates.ask_mate import ask_mate as ask_mate_processing
# from server.api.endpoints.mates.call_mate import call_mate as call_mate_processing
from server.api.endpoints.mates.create_mate import create_mate as create_mate_processing
from server.api.endpoints.mates.delete_mate import delete_mate as delete_mate_processing
from server.api.endpoints.mates.get_mate import get_mate as get_mate_processing
from server.api.endpoints.mates.get_mates import get_mates as get_mates_processing
from server.api.endpoints.mates.update_mate import update_mate as update_mate_processing

##########################################################
# Teams
##########################################################
from server.api.models.teams.teams_get_all import teams_get_all_output_example
from server.api.models.teams.teams_get_one import teams_get_one_output_example
from server.api.endpoints.teams.get_team import get_team as get_team_processing
from server.api.endpoints.teams.get_teams import get_teams as get_teams_processing

##########################################################
# Users
##########################################################
from server.api.models.users.users_create import (
    UsersCreateInput, UsersCreateOutput
)
from server.api.models.users.users_create_new_api_token import (
    UsersCreateNewApiTokenInput
)
from server.api.models.users.users_get_all import users_get_all_output_example
from server.api.models.users.users_get_one import UserGetOneInput, UserGetOneOutput, users_get_one_output_example
from server.api.models.users.users_replace_profile_picture import users_replace_profile_picture_output_example
from server.api.endpoints.users.create_new_api_token import create_new_api_token as create_new_api_token_processing
from server.api.endpoints.users.create_user import create_user as create_user_processing
from server.api.endpoints.users.get_user import get_user as get_user_processing
from server.api.endpoints.users.get_users import get_users as get_users_processing
from server.api.endpoints.users.replace_profile_picture import replace_profile_picture as replace_profile_picture_processing

##########################################################
# Skills
##########################################################
from server.api.models.apps.skills_get_one import skills_get_one_output_example
from server.api.endpoints.apps.get_skill import get_skill as get_skill_processing

##########################################################
# Tasks
##########################################################
from server.api.models.tasks.tasks_cancel import (
    TasksCancelOutput
)
from server.api.models.tasks.tasks_create import (
    Task
)
from server.api.models.tasks.tasks_get_task import tasks_get_task_output_example
from server.api.endpoints.tasks.cancel import cancel as tasks_cancel_processing
from server.api.endpoints.tasks.create import create as tasks_create_processing
from server.api.endpoints.tasks.get_task import get as tasks_get_task_processing

##########################################################
# Billing
##########################################################
from server.api.models.billing.billing_get_balance import (
    BillingBalanceOutput, BillingGetBalanceInput
)
from server.api.endpoints.billing.get_balance import get_balance as billing_get_balance_processing

##########################################################
# Server
##########################################################

##########################################################
# Apps
##########################################################

# AI
from server.api.models.apps.ai.skills_ai_ask import (
    AiAskInput, AiAskOutput, AiAskOutputStream
)
from server.api.models.apps.ai.skills_ai_estimate_cost import (
    AiEstimateCostInput, AiEstimateCostOutput
)
from server.api.endpoints.apps.ai.ask import ask as skill_ai_ask_processing
from server.api.endpoints.apps.ai.estimate_cost import estimate_cost as skill_ai_estimate_cost_processing

# Audio
from server.api.models.apps.audio.skills_audio_generate_transcript import (
    AudioGenerateTranscriptInput, AudioGenerateTranscriptOutput, AudioTranscriptAiProvider
)
# from server.api.endpoints.apps.audio.generate_transcript import generate_transcript as skill_audio_generate_transcript_processing

# Books
from server.api.endpoints.tasks.tasks import book_translate_task

# Docs
from server.api.models.apps.docs.skills_docs_create import (
    DocsCreateInput
)
from server.api.endpoints.apps.docs.create import create as skill_docs_create_processing

# Files
from server.api.models.apps.files.skills_files_delete import (
    FilesDeleteOutput
)
from server.api.models.apps.files.skills_files_upload import (
    FilesUploadOutput
)
from server.api.endpoints.apps.files.delete import delete as skill_files_delete_processing
from server.api.endpoints.apps.files.download import download as skill_files_download_processing
from server.api.endpoints.apps.files.upload import upload as skill_files_upload_processing

# Finance
from server.api.models.apps.finance.skills_finance_get_report import (
    FinanceGetReportInput, FinanceGetReportOutput
)
from server.api.models.apps.finance.skills_finance_get_transactions import (
    FinanceGetTransactionsInput, FinanceGetTransactionsOutput
)
from server.api.endpoints.apps.finance.get_report import get_report as skill_finance_get_report_processing
from server.api.endpoints.apps.finance.get_transactions import get_transactions as skill_finance_get_transactions_processing

# Health
from server.api.models.apps.health.skills_health_search_appointments import (
    HealthSearchAppointmentsInput, HealthSearchAppointmentsOutput
)
from server.api.models.apps.health.skills_health_search_doctors import (
    HealthSearchDoctorsInput, HealthSearchDoctorsOutput
)
from server.api.endpoints.apps.health.search_appointments import search_appointments as skill_health_search_appointments_processing
from server.api.endpoints.apps.health.search_doctors import search_doctors as skill_health_search_doctors_processing
from server.api.endpoints.tasks.tasks import health_search_appointments_task
from server.api.endpoints.tasks.tasks import health_search_doctors_task

# Home
from server.api.models.apps.home.skills_home_add_device import (
    HomeAddDeviceInput, HomeAddDeviceOutput
)
from server.api.models.apps.home.skills_home_set_scene import (
    HomeSetSceneInput, HomeSetSceneOutput
)
from server.api.models.apps.home.skills_home_set_device import (
    HomeSetDeviceInput, HomeSetDeviceOutput
)
from server.api.models.apps.home.skills_home_get_temperature import (
    HomeGetTemperatureInput, HomeGetTemperatureOutput
)
from server.api.models.apps.home.skills_home_get_power_consumption import (
    HomeGetPowerConsumptionInput, HomeGetPowerConsumptionOutput
)
from server.api.models.apps.home.skills_home_get_all_devices import (
    HomeGetAllDevicesInput, HomeGetAllDevicesOutput
)
from server.api.models.apps.home.skills_home_get_all_scenes import (
    HomeGetAllScenesInput, HomeGetAllScenesOutput
)
from server.api.models.apps.home.skills_home_add_scene import (
    HomeAddSceneInput, HomeAddSceneOutput
)
from server.api.endpoints.apps.home.get_all_devices import get_all_devices as skill_home_get_all_devices_processing
from server.api.endpoints.apps.home.get_all_scenes import get_all_scenes as skill_home_get_all_scenes_processing
from server.api.endpoints.apps.home.add_device import add_device as skill_home_add_device_processing
from server.api.endpoints.apps.home.add_scene import add_scene as skill_home_add_scene_processing
from server.api.endpoints.apps.home.set_scene import set_scene as skill_home_set_scene_processing
from server.api.endpoints.apps.home.set_device import set_device as skill_home_set_device_processing
from server.api.endpoints.apps.home.get_temperature import get_temperature as skill_home_get_temperature_processing
from server.api.endpoints.apps.home.get_power_consumption import get_power_consumption as skill_home_get_power_consumption_processing

# Maps
from server.api.models.apps.maps.skills_maps_search_places import (
    MapsSearchInput, MapsSearchOutput
)
from server.api.endpoints.apps.maps.search_places import search_places as skill_maps_search_processing

# Messages
from server.api.models.apps.messages.skills_connect_server import (
    MessagesConnectInput, MessagesConnectOutput
)
from server.api.models.apps.messages.skills_send_message import (
    MessagesSendInput, MessagesSendOutput
)
from server.api.endpoints.apps.messages.connect import connect as skill_messages_connect_processing
from server.api.endpoints.apps.messages.send import send as skill_messages_send_processing

# PDF Editor
# will be placed here...

# Photos
from server.api.models.apps.photos.skills_photos_resize_image import photos_resize_output_example
from server.api.endpoints.apps.photos.resize_image import resize_image as skill_photos_resize_image_processing

# Travel
from server.api.models.apps.travel.skills_travel_search_connections import (
    TravelSearchConnectionsInput, TravelSearchConnectionsOutput
)
from server.api.endpoints.apps.travel.search_connections import search_connections as skill_travel_search_connections_processing

# Videos
from server.api.models.apps.videos.skills_videos_get_transcript import (
    VideosGetTranscriptInput, VideosGetTranscriptOutput
)
from server.api.endpoints.apps.videos.get_transcript import get_transcript as skill_videos_get_transcript_processing

# Web
from server.api.models.apps.web.skills_web_read import (
    WebReadInput, WebReadOutput
)
from server.api.models.apps.web.skills_web_view import (
    WebViewInput, WebViewOutput
)
from server.api.endpoints.apps.web.read import read as skill_web_read_processing
from server.api.endpoints.apps.web.view import view as skill_web_view_processing

# Import parameters and metadata
from server.api.docs.parameters import (
    mates_endpoints,
    teams_endpoints,
    users_endpoints,
    skills_endpoints,
    tasks_endpoints,
    billing_endpoints,
    server_endpoints,
    apps_ai_endpoints,
    apps_audio_endpoints,
    apps_books_endpoints,
    apps_docs_endpoints,
    apps_files_endpoints,
    apps_finance_endpoints,
    apps_health_endpoints,
    apps_home_endpoints,
    apps_maps_endpoints,
    apps_messages_endpoints,
    apps_photos_endpoints,
    apps_travel_endpoints,
    apps_videos_endpoints,
    apps_web_endpoints,
    input_parameter_descriptions
)
