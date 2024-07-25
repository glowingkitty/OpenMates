
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

import base64


from server.api.models.files.files_upload import (
    FileUploadOutput
)
from server.api.models.mates.mates_ask import (
    MatesAskOutput
)
from server.api.models.mates.mates_get_all import (
    MatesGetAllOutput
)
from server.api.models.mates.mates_get_one import (
    Mate
)
from server.api.models.mates.mates_create import (
    MatesCreateOutput
)
from server.api.models.mates.mates_update import (
    MatesUpdateOutput
)
from server.api.models.users.users_get_all import (
    UsersGetAllOutput
)
from server.api.models.users.users_get_one import (
    User
)
from server.api.models.skills.skills_get_one import (
    Skill
)
from server.api.models.users.users_create import (
    UsersCreateOutput
)
from server.api.models.users.users_create_new_api_token import (
    UsersCreateNewApiTokenOutput
)
from server.api.models.users.users_replace_profile_picture import (
    UsersReplaceProfilePictureOutput
)
from server.api.models.skills.youtube.skills_youtube_get_transcript import (
    YouTubeGetTranscriptOutput
)
from server.api.models.skills.atopile.skills_atopile_create_pcb_schematic import (
    AtopileCreatePcbSchematicOutput
)
from server.api.models.skills.chatgpt.skills_chatgpt_ask import (
    ChatGPTAskOutput
)
from server.api.models.skills.akaunting.skills_akaunting_get_report import (
    AkauntingGetReportOutput
)
from server.api.models.skills.akaunting.skills_akaunting_create_expense import (
    AkauntingCreateExpenseOutput
)
from server.api.models.skills.akaunting.skills_akaunting_create_income import (
    AkauntingCreateIncomeOutput
)
from server.api.models.teams.teams_get_all import (
    TeamsGetAllOutput
)


def generate_responses(status_codes):
    descriptions = {
        "200": "Successful Response",
        "201": "Successful Creation",
        "400": "Bad Request",
        "401": "Unauthorized",
        "403": "Forbidden",
        "404": "Not Found",
        "409": "Conflict",
        "422": "Validation Error",
        "500": "Internal Server Error"
    }

    responses = {}
    for code in status_codes:
        responses[str(code)] = {"description": descriptions.get(str(code), "Unknown Status Code"), "model": None}

    return responses


def set_example(openapi_schema, path, method, request_or_response, example, response_code=None):
    # Ensure the path exists
    if path not in openapi_schema["paths"]:
        openapi_schema["paths"][path] = {}

    # Ensure the method exists
    if method not in openapi_schema["paths"][path]:
        openapi_schema["paths"][path][method] = {}

    # Ensure the request_or_response exists
    if request_or_response not in openapi_schema["paths"][path][method]:
        openapi_schema["paths"][path][method][request_or_response] = {}

    if request_or_response == "responses":
        # Ensure the response_code exists
        if response_code not in openapi_schema["paths"][path][method][request_or_response]:
            openapi_schema["paths"][path][method][request_or_response][response_code] = {}

        # Ensure the 'content' exists
        if "content" not in openapi_schema["paths"][path][method][request_or_response][response_code]:
            openapi_schema["paths"][path][method][request_or_response][response_code]["content"] = {}

        # Check if the example is an image
        if isinstance(example, dict) and "image/jpeg" in example:
            openapi_schema["paths"][path][method][request_or_response][response_code]["content"] = {
                "image/jpeg": {
                    "schema": {
                        "type": "string",
                        "format": "binary"
                    },
                    "example": example["image/jpeg"]
                }
            }
        else:
            # Ensure the 'application/json' exists
            if "application/json" not in openapi_schema["paths"][path][method][request_or_response][response_code]["content"]:
                openapi_schema["paths"][path][method][request_or_response][response_code]["content"]["application/json"] = {}

            # Set the example
            openapi_schema["paths"][path][method][request_or_response][response_code]["content"]["application/json"]["example"] = example
    else:
        # Ensure the 'content' exists
        if "content" not in openapi_schema["paths"][path][method][request_or_response]:
            openapi_schema["paths"][path][method][request_or_response]["content"] = {}

        # Ensure the 'application/json' exists
        if "application/json" not in openapi_schema["paths"][path][method][request_or_response]["content"]:
            openapi_schema["paths"][path][method][request_or_response]["content"]["application/json"] = {}

        # Set the example
        openapi_schema["paths"][path][method][request_or_response]["content"]["application/json"]["example"] = example


files_endpoints = {
   "upload_file":{
        "response_model":FileUploadOutput,
        "summary": "Upload",
        "description": "<img src='images/files/upload.png' alt='Upload an image to the OpenMates server, so you can use it as a profile picture.'>",
        "responses": generate_responses([200, 400, 401, 403, 409, 422, 500]),
    }
}

mates_endpoints = {
    "ask_mate":{
        "response_model":MatesAskOutput,
        "summary": "Ask",
        "description": "<img src='images/mates/ask.png' alt='Send a ask to one of your AI team mates. It will then automatically decide what skills to use to answer your question or fulfill the task.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    "get_all_mates":{
        "response_model":MatesGetAllOutput,
        "summary": "Get all",
        "description": "<img src='images/mates/get_all.png' alt='Get an overview list of all AI team mates currently active on the OpenMates server.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500]),
    },
    "get_mate":{
        "response_model":Mate,
        "summary": "Get mate",
        "description": "<img src='images/mates/get_mate.png' alt='Get all details about a specific mate. Including system prompt, available skills and more.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500])
    },
    "create_mate":{
        "response_model":MatesCreateOutput,
        "summary": "Create",
        "description": "<img src='images/mates/create.png' alt='Create a new mate on the OpenMates server, with a custom system prompt, accessible skills and other settings.'>",
        "responses": generate_responses([201, 400, 401, 403, 409, 422, 500]),
        "status_code": 201
    },
    "update_mate":{
        "response_model":MatesUpdateOutput,
        "summary": "Update",
        "description": "<img src='images/mates/update.png' alt='Update an existing mate on the server. For example change the system prompt, the available skills and more.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 409, 422, 500])
    },
    "delete_mate":{
        "summary": "Delete",
        "description": "<img src='images/mates/delete.png' alt='Delete an existing mate on the server.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500])
    }
}

skills_endpoints = {
    "get_skill":{
        "response_model":Skill,
        "summary": "Get skill",
        "description": "<img src='images/skills/get_skill.png' alt='Get all details about a specific skill.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500])
    }
}

skills_chatgpt_endpoints = {
    "ask_chatgpt":{
        "response_model":ChatGPTAskOutput,
        "summary": "ChatGPT | Ask",
        "description": "<img src='images/skills/chatgpt/ask.png' alt='Ask ChatGPT from OpenAI a question, and it will answer it based on its knowledge.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

skills_claude_endpoints = {
    "ask_claude":{
        # "response_model":ClaudeAskOutput,
        "summary": "Claude | Ask",
        "description": "<img src='images/skills/claude/ask.png' alt='Ask Claude from Anthropic a question, and it will answer it based on its knowledge.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

skills_youtube_endpoints = {
    "ask_youtube":{
        # "response_model":YouTubeAskOutput,
        "summary": "YouTube | Ask",
        "description": "<img src='images/skills/youtube/ask.png' alt='Answers your question about one or multiple videos, using their transcripts and details.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    "get_transcript":{
        "response_model":YouTubeGetTranscriptOutput,
        "summary": "YouTube | Get transcript",
        "description": "<img src='images/skills/youtube/transcript.png' alt='Get the full transcript of a YouTube video.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

skills_atopile_endpoints = {
    "create_pcb_schematic":{
        "response_model":AtopileCreatePcbSchematicOutput,
        "summary": "Atopile | Create PCB schematic",
        "description": "<img src='images/skills/atopile/create_pcb_schematic.png' alt='Creates a PCB schematic based on a datasheet, component name or component requirements.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

skills_akaunting_endpoints = {
    "get_report":{
        "response_model":AkauntingGetReportOutput,
        "summary": "Akaunting | Get report",
        "description": "<img src='images/skills/akaunting/get_report.png' alt='Get a report from Akaunting.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    "create_expense":{
        "response_model":AkauntingCreateExpenseOutput,
        "summary": "Akaunting | Create Expense",
        "description": "<img src='images/skills/akaunting/create_expense.png' alt='Create a new purchase, refund or other expense in Akaunting. Including the vendor, bill and bank transaction.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    "create_income":{
        "response_model":AkauntingCreateIncomeOutput,
        "summary": "Akaunting | Create Income",
        "description": "<img src='images/skills/akaunting/create_income.png' alt='Create a new sale, refund or other income in Akaunting. Including the customer, invoice and bank transaction.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

skills_image_editor_endpoints = {
     "resize_image":{
        "summary": "Image Editor | Resize",
        "description": "<img src='images/skills/image_editor/resize.png' alt='Scale or crop an existing image to a higher or lower resolution. Can also use AI upscaling for even better results.'>",
        "responses": {
            "200": {
                "description": "Successful Response",
                "content": {
                    "image/jpeg": {
                        "schema": {
                            "type": "string",
                            "format": "binary"
                        }
                    }
                }
            },
            "400": {"description": "Bad Request"},
            "401": {"description": "Unauthorized"},
            "403": {"description": "Forbidden"},
            "404": {"description": "Not Found"},
            "422": {"description": "Validation Error"},
            "500": {"description": "Internal Server Error"}
        }
    }
}

users_endpoints = {
    "get_all_users":{
        "response_model":UsersGetAllOutput,
        "summary": "Get all",
        "description": "<img src='images/users/get_all.png' alt='Get an overview list of all users in a team.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500])
    },
    "get_user":{
        "response_model":User,
        "summary": "Get user",
        "description": "<img src='images/users/get_user.png' alt='Get all details about a specific user.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500])
    },
    "create_user":{
        "response_model":UsersCreateOutput,
        "summary": "Create",
        "description": "<img src='images/users/create.png' alt='Create a new user in a team.'>",
        "responses": generate_responses([201, 400, 401, 403, 409, 422, 500]),
        "status_code": 201
    },
    "update_user":{
        "response_model":User,
        "summary": "Update",
        "description": "<img src='images/users/update.png' alt='Update your user account details. Change privacy settings, email address and more.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 409, 422, 500])
    },
    "replace_profile_picture":{
        "response_model":UsersReplaceProfilePictureOutput,
        "summary": "Replace profile picture",
        "description": "<img src='images/users/replace_profile_picture.png' alt='Replace the current profile picture with a new one. The old picture will be deleted.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 409, 422, 500])
    },
    "create_new_api_token":{
        "response_model":UsersCreateNewApiTokenOutput,
        "summary": "Create new API token",
        "description": "<img src='images/users/create_new_api_token.png' alt='Creates a new API token for your account. Your previous token will be deleted.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

teams_endpoints = {
    "get_all_teams":{
        "response_model":TeamsGetAllOutput,
        "summary": "Get all",
        "description": "<img src='images/teams/get_all.png' alt='Get an overview list of all teams on your OpenMates server.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500])
    }
}

server_endpoints = {
    "get_status":{
        "summary": "Get status",
        "description": "<img src='images/server/status.png' alt='Get a summary of your current server status.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500])
    },
    "get_settings":{
        "summary": "Get settings",
        "description": "<img src='images/server/get_settings.png' alt='Get all the current settings of your OpenMates server.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500])
    },
    "update_settings":{
        "summary": "Update settings",
        "description": "<img src='images/server/update_settings.png' alt='Update any of the setting on your OpenMates server.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 409, 422, 500])
    }
}


tags_metadata = [
    {
        "name": "Mates",
        "description": "<img src='images/mates.png' alt='Mates are your AI team members. They can help you with various tasks. Each mate is specialized in a different area.'>"
    },
    {
        "name": "Software",
        "description": "<img src='images/software.png' alt='Your team mates can interact with a wide range of software, on your behalf. For example: ChatGPT, Notion, RSS, SevDesk, YouTube, Claude, StableDiffusion, Firefox, Dropbox.'>"
    },
    {
        "name": "Skills",
        "description": "<img src='images/skills.png' alt='Your team mate can use a wide range of software skills. Or, you can call them directly via the API.'>"
    },
    {
        "name": "Workflows",
        "description": "<img src='images/workflows.png' alt='A skill is powerful. Combining multiple skills in a workflow is magical.'>"
    },
    {
        "name": "Tasks",
        "description": "<img src='images/tasks.png' alt='A task is a scheduled run of a single skill or a whole workflow. It can happen once, or repeated.'>"
    },
    {
        "name": "Billing",
        "description": "<img src='images/billing.png' alt='Manage your billing settings, download invoices and more.'>"
    },
    {
        "name": "Server",
        "description": "<img src='images/server.png' alt='Manage your OpenMates server. Change settings, see how the server is doing and more.'>"
    },
    {
        "name": "Teams",
        "description": "<img src='images/teams.png' alt='Manage the teams on your OpenMates server.'>"
    },
    {
        "name": "Users",
        "description": "<img src='images/users.png' alt='Manage user accounts of a team. A user can get personalized responses from mates and access to the OpenMates API.'>"
    }
]


input_parameter_descriptions = {
    "team_slug": {
        "description": "The URL friendly name of your team",
        "examples": ["openmates_enthusiasts"]
    },
    "username": {
        "description": "Your username",
        "examples": ["sophiarocks212"]
    },
    "token": {
        "description": "Your API token",
        "examples": ["123456789"]
    },
    "mate_username":{
        "description": "The username of the AI team mate",
        "examples": ["sophia"]
    },
    "user_username":{
        "description": "The username of the user",
        "examples": ["kitty"]
    },
    "file": {
        "description": "The bytes of the file to upload"
    },
    "software_slug": {
        "description": "The slug of the software",
        "examples": ["claude"]
    },
    "skill_slug": {
        "description": "The slug of the skill",
        "examples": ["ask"]
    }
}

