from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBearer
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import os

##########################################################
# Mates
##########################################################
from server.api.models.mates.mates_ask import (
    MatesAskOutput,
    mates_ask_input_example, mates_ask_output_example
)
from server.api.models.mates.mates_create import (
    MatesCreateOutput,
    mates_create_input_example, mates_create_output_example
)
from server.api.models.mates.mates_delete import (
    MatesDeleteOutput,
    mates_delete_output_example
)
from server.api.models.mates.mates_get_all import (
    MatesGetAllOutput,
    mates_get_all_output_example
)
from server.api.models.mates.mates_get_one import (
    Mate,
    mates_get_one_output_example
)
from server.api.models.mates.mates_update import (
    MatesUpdateOutput,
    mates_update_input_example, mates_update_output_example
)


##########################################################
# Teams
##########################################################
from server.api.models.teams.teams_get_all import (
    TeamsGetAllOutput,
    teams_get_all_output_example
)
from server.api.models.teams.teams_get_one import (
    Team,
    teams_get_one_output_example
)


##########################################################
# Users
##########################################################
from server.api.models.users.users_create import (
    UsersCreateOutput,
    users_create_input_example, users_create_output_example
)
from server.api.models.users.users_create_new_api_token import (
    UsersCreateNewApiTokenOutput,
    users_create_new_api_token_input_example, users_create_new_api_token_output_example
)
from server.api.models.users.users_get_all import (
    UsersGetAllOutput,
    users_get_all_output_example
)
from server.api.models.users.users_get_one import (
    User,
    users_get_one_output_example
)
from server.api.models.users.users_replace_profile_picture import (
    UsersReplaceProfilePictureOutput,
    users_replace_profile_picture_output_example
)


##########################################################
# Skills
##########################################################
from server.api.models.apps.skills_get_one import (
    Skill
)


##########################################################
# Tasks
##########################################################
from server.api.models.tasks.tasks_create import (
    Task
)
from server.api.models.tasks.tasks_cancel import (
    TasksCancelOutput
)


##########################################################
# Billing
##########################################################
from server.api.models.billing.billing_get_balance import (
    BillingBalanceOutput,
    billing_get_balance_input_example, billing_get_balance_output_example
)


##########################################################
# Tasks
##########################################################
from server.api.models.tasks.tasks_cancel import (
    tasks_cancel_output_example
)
from server.api.models.tasks.tasks_create import (
    task_create_output_example
)
from server.api.models.tasks.tasks_get_task import tasks_get_task_output_example





##########################################################
# Apps
##########################################################

# AI
from server.api.models.apps.ai.skills_ai_ask import (
    AiAskOutput,
    AiAskOutputStream,
    ai_ask_input_example, ai_ask_input_example_2, ai_ask_input_example_3,
    ai_ask_input_example_4, ai_ask_input_example_5, ai_ask_output_example, 
    ai_ask_output_example_2, ai_ask_output_example_3, ai_ask_output_example_4, 
    ai_ask_output_example_5
)
from server.api.models.apps.ai.skills_ai_estimate_cost import (
    AiEstimateCostOutput,
    ai_estimate_cost_input_example, ai_estimate_cost_output_example
)

# Audio
from server.api.models.apps.audio.skills_audio_generate_transcript import (
    AudioGenerateTranscriptOutput
)

# Books
from server.api.models.apps.books.skills_books_translate import (
    books_translate_output_task_example
)

# Docs
from server.api.models.apps.docs.skills_docs_create import (
    docs_create_input_example, docs_create_output_example
)

# Files
from server.api.models.apps.files.skills_files_delete import (
    FilesDeleteOutput,
    files_delete_output_example
)
from server.api.models.apps.files.skills_files_upload import (
    FilesUploadOutput,
    files_upload_output_example
)

# Finance
from server.api.models.apps.finance.skills_finance_get_report import (
    FinanceGetReportOutput,
    finance_get_report_input_example, finance_get_report_output_example
)
from server.api.models.apps.finance.skills_finance_get_transactions import (
    FinanceGetTransactionsOutput,
    finance_get_transactions_input_example, finance_get_transactions_output_example
)

# Health
from server.api.models.apps.health.skills_health_search_appointments import (
    HealthSearchAppointmentsOutput,
    health_search_appointments_input_example, health_search_appointments_output_task_example
)
from server.api.models.apps.health.skills_health_search_doctors import (
    HealthSearchDoctorsOutput,
    health_search_doctors_input_example, health_search_doctors_output_task_example
)

# Home
from server.api.models.apps.home.skills_home_add_device import (
    HomeAddDeviceOutput,
    home_add_device_input_example, home_add_device_output_example
)
from server.api.models.apps.home.skills_home_add_scene import (
    HomeAddSceneOutput,
    home_add_scene_input_example, home_add_scene_output_example
)
from server.api.models.apps.home.skills_home_get_all_devices import (
    HomeGetAllDevicesOutput,
    home_get_all_devices_input_example, home_get_all_devices_output_example
)
from server.api.models.apps.home.skills_home_get_all_scenes import (
    HomeGetAllScenesOutput,
    home_get_all_scenes_input_example, home_get_all_scenes_output_example
)
from server.api.models.apps.home.skills_home_get_temperature import (
    HomeGetTemperatureOutput,
    home_get_temperature_input_example, home_get_temperature_output_example
)
from server.api.models.apps.home.skills_home_get_power_consumption import (
    HomeGetPowerConsumptionOutput,
    home_get_power_consumption_input_example, home_get_power_consumption_output_example
)
from server.api.models.apps.home.skills_home_set_device import (
    HomeSetDeviceOutput,
    home_set_device_input_example, home_set_device_output_example
)
from server.api.models.apps.home.skills_home_set_scene import (
    HomeSetSceneOutput,
    home_set_scene_input_example, home_set_scene_output_example
)

# Maps
from server.api.models.apps.maps.skills_maps_search_places import (
    MapsSearchOutput,
    maps_search_input_example, maps_search_output_task_example
)

# Messages
from server.api.models.apps.messages.skills_connect_server import (
    MessagesConnectOutput,
    messages_connect_input_example, messages_connect_output_example
)
from server.api.models.apps.messages.skills_send_message import (
    MessagesSendOutput,
    messages_send_input_example, messages_send_output_example
)

# PDF Editor
# will be placed here...

# Photos
from server.api.models.apps.photos.skills_photos_resize_image import photos_resize_output_example

# Travel
from server.api.models.apps.travel.skills_travel_search_connections import (
    TravelSearchConnectionsOutput,
    travel_search_connections_input_example, travel_search_connections_output_task_example
)

# Videos
from server.api.models.apps.videos.skills_videos_get_transcript import (
    VideosGetTranscriptOutput,
    videos_get_transcript_input_example, videos_get_transcript_output_example
)

# Web
from server.api.models.apps.web.skills_web_read import (
    WebReadOutput,
    web_read_input_example, web_read_output_example
)
from server.api.models.apps.web.skills_web_view import (
    WebViewOutput,
    web_view_input_example, web_view_output_example
)


##########################################################
# Parameters
##########################################################
from server.api.docs.parameters import (
    tags_metadata
)