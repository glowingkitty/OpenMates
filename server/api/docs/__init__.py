from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBearer
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import os

# Import examples
from server.api.models.billing.billing_get_balance import (
    billing_get_balance_input_example, billing_get_balance_output_example
)
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
from server.api.models.apps.ai.skills_ai_ask import (
    ai_ask_input_example, ai_ask_input_example_2, ai_ask_input_example_3,
    ai_ask_input_example_4, ai_ask_input_example_5, ai_ask_output_example, ai_ask_output_example_2, ai_ask_output_example_3,
    ai_ask_output_example_4, ai_ask_output_example_5
)
from server.api.models.apps.ai.skills_ai_estimate_cost import (
    ai_estimate_cost_input_example, ai_estimate_cost_output_example
)
from server.api.models.apps.code.skills_code_plan import (
    code_plan_input_example, code_plan_input_example_2, code_plan_output_example, code_plan_output_example_2
)
from server.api.models.apps.code.skills_code_write import (
    code_write_input_example, code_write_output_example
)
from server.api.models.apps.docs.skills_docs_create import (
    docs_create_input_example, docs_create_output_example
)
from server.api.models.apps.finance.skills_finance_get_report import (
    finance_get_report_input_example, finance_get_report_output_example
)
from server.api.models.apps.finance.skills_finance_get_transactions import (
    finance_get_transactions_input_example, finance_get_transactions_output_example
)
from server.api.models.apps.files.skills_files_delete import (
    files_delete_output_example
)
from server.api.models.apps.files.skills_files_upload import (
    files_upload_output_example
)
from server.api.models.apps.messages.skills_connect_server import (
    messages_connect_input_example, messages_connect_output_example
)
from server.api.models.apps.messages.skills_send_message import (
    skills_send_message_input_example, skills_send_message_output_example
)
from server.api.models.apps.photos.skills_photos_resize_image import photos_resize_output_example
from server.api.models.apps.skills_get_one import skills_get_one_output_example
from server.api.models.apps.videos.skills_videos_get_transcript import (
    videos_get_transcript_input_example, videos_get_transcript_output_example
)
from server.api.models.apps.web.skills_web_read import (
    web_read_input_example, web_read_output_example
)
from server.api.models.apps.web.skills_web_view import (
    web_view_input_example, web_view_output_example
)
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
from server.api.models.apps.business.skills_business_create_pitch import (
    business_create_pitch_input_example, business_create_pitch_output_example
)
from server.api.models.apps.business.skills_business_create_application import (
    business_create_application_input_example, business_create_application_output_example
)
from server.api.models.apps.business.skills_business_plan_application import (
    business_plan_application_input_example, business_plan_application_output_example
)
from server.api.models.tasks.tasks_cancel import (
    tasks_cancel_output_example
)
from server.api.models.tasks.tasks_create import (
    task_create_output_example
)
from server.api.models.tasks.tasks_get_task import tasks_get_task_output_example
from server.api.models.teams.teams_get_all import teams_get_all_output_example
from server.api.models.teams.teams_get_one import teams_get_one_output_example
from server.api.models.users.users_create import (
    users_create_input_example, users_create_output_example
)
from server.api.models.users.users_create_new_api_token import (
    users_create_new_api_token_input_example, users_create_new_api_token_output_example
)
from server.api.models.users.users_get_all import users_get_all_output_example
from server.api.models.users.users_get_one import users_get_one_output_example
from server.api.models.users.users_replace_profile_picture import users_replace_profile_picture_output_example

# Import set_example function
from server.api.docs.parameters import (
    set_example, tags_metadata
)