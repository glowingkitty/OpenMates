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
    mates_ask_input_example, mates_ask_output_example
)
from server.api.models.mates.mates_create import (
    mates_create_input_example, mates_create_output_example
)
from server.api.models.mates.mates_delete import mates_delete_output_example
from server.api.models.mates.mates_get_all import mates_get_all_output_example
from server.api.models.mates.mates_get_one import mates_get_one_output_example
from server.api.models.mates.mates_update import (
    mates_update_input_example, mates_update_output_example
)


##########################################################
# Teams
##########################################################
from server.api.models.teams.teams_get_all import teams_get_all_output_example
from server.api.models.teams.teams_get_one import teams_get_one_output_example


##########################################################
# Users
##########################################################
from server.api.models.users.users_create import (
    users_create_input_example, users_create_output_example
)
from server.api.models.users.users_create_new_api_token import (
    users_create_new_api_token_input_example, users_create_new_api_token_output_example
)
from server.api.models.users.users_get_all import users_get_all_output_example
from server.api.models.users.users_get_one import users_get_one_output_example
from server.api.models.users.users_replace_profile_picture import users_replace_profile_picture_output_example


##########################################################
# Skills
##########################################################
# will be placed here...


##########################################################
# Tasks
##########################################################
# will be placed here...


##########################################################
# Billing
##########################################################
from server.api.models.billing.billing_get_balance import (
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
# Parameters
##########################################################
from server.api.docs.parameters import (
    set_example, tags_metadata
)


##########################################################
# Apps
##########################################################

# AI
from server.api.models.apps.ai.skills_ai_ask import (
    ai_ask_input_example, ai_ask_input_example_2, ai_ask_input_example_3,
    ai_ask_input_example_4, ai_ask_input_example_5, ai_ask_output_example, 
    ai_ask_output_example_2, ai_ask_output_example_3, ai_ask_output_example_4, 
    ai_ask_output_example_5
)
from server.api.models.apps.ai.skills_ai_estimate_cost import (
    ai_estimate_cost_input_example, ai_estimate_cost_output_example
)

# Audio
# will be placed here...

# Books
# will be placed here...

# Docs
from server.api.models.apps.docs.skills_docs_create import (
    docs_create_input_example, docs_create_output_example
)

# Files
from server.api.models.apps.files.skills_files_delete import (
    files_delete_output_example
)
from server.api.models.apps.files.skills_files_upload import (
    files_upload_output_example
)

# Finance
from server.api.models.apps.finance.skills_finance_get_report import (
    finance_get_report_input_example, finance_get_report_output_example
)
from server.api.models.apps.finance.skills_finance_get_transactions import (
    finance_get_transactions_input_example, finance_get_transactions_output_example
)

# Health
from server.api.models.apps.health.skills_health_search_appointments import (
    health_search_appointments_input_example, health_search_appointments_output_example
)
from server.api.models.apps.health.skills_health_search_doctors import (
    health_search_doctors_input_example, health_search_doctors_output_example
)

# Home
from server.api.models.apps.home.skills_home_add_device import (
    home_add_device_input_example, home_add_device_output_example
)
from server.api.models.apps.home.skills_home_add_scene import (
    home_add_scene_input_example, home_add_scene_output_example
)
from server.api.models.apps.home.skills_home_get_all_devices import (
    home_get_all_devices_input_example, home_get_all_devices_output_example
)
from server.api.models.apps.home.skills_home_get_all_scenes import (
    home_get_all_scenes_input_example, home_get_all_scenes_output_example
)
from server.api.models.apps.home.skills_home_get_temperature import (
    home_get_temperature_input_example, home_get_temperature_output_example
)
from server.api.models.apps.home.skills_home_get_power_consumption import (
    home_get_power_consumption_input_example, home_get_power_consumption_output_example
)
from server.api.models.apps.home.skills_home_set_device import (
    home_set_device_input_example, home_set_device_output_example
)
from server.api.models.apps.home.skills_home_set_scene import (
    home_set_scene_input_example, home_set_scene_output_example
)

# Maps
from server.api.models.apps.maps.skills_maps_search import (
    maps_search_input_example, maps_search_output_example
)

# Messages
from server.api.models.apps.messages.skills_connect_server import (
    messages_connect_input_example, messages_connect_output_example
)
from server.api.models.apps.messages.skills_send_message import (
    skills_send_message_input_example, skills_send_message_output_example
)

# PDF Editor
# will be placed here...

# Photos
from server.api.models.apps.photos.skills_photos_resize_image import photos_resize_output_example

# Travel
from server.api.models.apps.travel.skills_travel_search_connections import (
    travel_search_connections_input_example, travel_search_connections_output_example
)

# Videos
from server.api.models.apps.videos.skills_videos_get_transcript import (
    videos_get_transcript_input_example, videos_get_transcript_output_example
)

# Web
from server.api.models.apps.web.skills_web_read import (
    web_read_input_example, web_read_output_example
)
from server.api.models.apps.web.skills_web_view import (
    web_view_input_example, web_view_output_example
)