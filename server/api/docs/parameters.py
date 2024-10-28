from server.api.docs import *
from typing import Union

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


##########################################################
# Mates
##########################################################
mates_endpoints = {
    # /v1/{team_slug}/mates/ask
    "ask_mate":{
        "response_model":Task,
        "summary": "Ask",
        "description": "<img src='images/mates/ask.png' alt='Send a ask to one of your AI team mates. It will then automatically decide what skills to use to answer your question or fulfill the task.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    # /v1/{team_slug}/mates/
    "get_all_mates":{
        "response_model":MatesGetAllOutput,
        "summary": "Get all",
        "description": "<img src='images/mates/get_all.png' alt='Get an overview list of all AI team mates currently active on the OpenMates server.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500]),
    },
    "create_mate":{
        "response_model":MatesCreateOutput,
        "summary": "Create",
        "description": "<img src='images/mates/create.png' alt='Create a new mate on the OpenMates server, with a custom system prompt, accessible skills and other settings.'>",
        "responses": generate_responses([201, 400, 401, 403, 409, 422, 500]),
        "status_code": 201
    },
    # /v1/{team_slug}/mates/{mate_username}
    "get_mate":{
        "response_model":Mate,
        "summary": "Get mate",
        "description": "<img src='images/mates/get_mate.png' alt='Get all details about a specific mate. Including system prompt, available skills and more.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500])
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


##########################################################
# Teams
##########################################################
teams_endpoints = {
    # /v1/teams
    "get_all_teams":{
        "response_model":TeamsGetAllOutput,
        "summary": "Get all",
        "description": "<img src='images/teams/get_all.png' alt='Get an overview list of all teams on your OpenMates server.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500])
    },
    # /v1/{team_slug}
    "get_team":{
        "response_model":Team,
        "summary": "Get team",
        "description": "<img src='images/teams/get_team.png' alt='Get all details about a specific team. Including the skill settings, privacy and more.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500])
    }
}


##########################################################
# Users
##########################################################
users_endpoints = {
    # /v1/{team_slug}/users/
    "get_all_users":{
        "response_model":UsersGetAllOutput,
        "summary": "Get all",
        "description": "<img src='images/users/get_all.png' alt='Get an overview list of all users in a team.'>",
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
    # /v1/{team_slug}/users/{username}
    "get_user":{
        "response_model":dict,
        "summary": "Get user",
        "description": "<img src='images/users/get_user.png' alt='Get all details about a specific user.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500])
    },
    # /v1/{team_slug}/users/{username}/profile_picture
    "replace_profile_picture":{
        "response_model":UsersReplaceProfilePictureOutput,
        "summary": "Replace profile picture",
        "description": "<img src='images/users/replace_profile_picture.png' alt='Replace the current profile picture with a new one. The old picture will be deleted.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 409, 422, 500])
    },
    # /v1/api_token
    "create_new_api_token":{
        "response_model":UsersCreateNewApiTokenOutput,
        "summary": "Create new API token",
        "description": "<img src='images/users/create_new_api_token.png' alt='Creates a new API token for your account. Your previous token will be deleted.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}


##########################################################
# Skills
##########################################################
skills_endpoints = {
    "get_skill":{
        "response_model":Skill,
        "summary": "Get skill",
        "description": "<img src='images/apps/get_skill.png' alt='Get all details about a specific skill.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500])
    }
}


##########################################################
# Tasks
##########################################################
tasks_endpoints = {
    # /v1/{team_slug}/tasks/{task_id}
    "get_task":{
        "response_model":Task,
        "summary": "Get task",
        "description": "<img src='images/tasks/get_task.png' alt='Get a specific task, its status and if available its result.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    "cancel":{
        "response_model":TasksCancelOutput,
        "summary": "Cancel",
        "description": "<img src='images/tasks/cancel.png' alt='Cancel a specific task. If its already running, it will be gracefully stopped.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}


##########################################################
# Billing
##########################################################
billing_endpoints = {
    "get_balance":{
        "response_model":BillingBalanceOutput,
        "summary": "Get balance",
        "description": "<img src='images/billing/get_balance.png' alt='Get your current available balance in credits for your team or user account.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}


##########################################################
# Server
##########################################################
server_endpoints = {
    # /v1/status
    "get_status":{
        "summary": "Get status",
        "description": "<img src='images/server/status.png' alt='Get a summary of your current server status.'>",
        "responses": generate_responses([200, 401, 403, 404, 422, 500])
    },
    # /v1/settings
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


##########################################################
# Apps
##########################################################

# AI
apps_ai_endpoints = {
    # /v1/{team_slug}/apps/ai/ask
    "ask":{
        "response_model": Union[AiAskOutput, AiAskOutputStream],
        "summary": "Skill | Ask",
        "description": "<img src='images/apps/ai/ask.png' alt='Ask your AI a question using text & images, and it will answer it based on its knowledge.'>",
        "responses": {
            200: {
                "description": "Successful Response",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/AiAskOutput"}
                    },
                    "text/event-stream": {
                        "schema": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/AiAskOutputStream"}
                        }
                    }
                }
            },
            **generate_responses([400, 401, 403, 404, 422, 500])
        }
    },
    # /v1/{team_slug}/apps/ai/estimate_cost
    "estimate_cost":{
        "response_model":AiEstimateCostOutput,
        "summary": "Skill | Estimate Cost",
        "description": "<img src='images/apps/ai/estimate_cost.png' alt='Get the estimated cost of a request to your AI.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

# Audio
apps_audio_endpoints = {
    # /v1/{team_slug}/apps/audio/generate_transcript
    "generate_transcript": {
        "response_model": AudioGenerateTranscriptOutput,
        "summary": "Skill | Generate transcript",
        "description": "<img src='images/apps/audio/generate_transcript.png' alt='Transform spoken audio to text.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

# Books
apps_books_endpoints = {
    # /v1/{team_slug}/apps/books/translate
    "translate": {
        "response_model": Task,
        "summary": "Skill | Translate",
        "description": "<img src='images/apps/books/translate.png' alt='Translate a book that was written by you to another language.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
}

# Docs
apps_docs_endpoints = {
    # /v1/{team_slug}/apps/docs/create
    "create":{
        "response_model":FilesUploadOutput,
        "summary": "Skill | Create",
        "description": "<img src='images/apps/docs/create.png' alt='Create a new document. Including paragraphs, images, tables and more.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

# Files
apps_files_endpoints = {
    # /v1/{team_slug}/apps/files/upload
    "upload": {
        "response_model": FilesUploadOutput,
        "summary": "Skill | Upload",
        "description": "<img src='images/apps/files/upload.png' alt='Upload a file or folder to the OpenMates server or to a cloud storage account.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    # /v1/{team_slug}/apps/files/{provider}/{file_path}
    "download": {
        "summary": "Skill | Download",
        "description": "<img src='images/apps/files/download.png' alt='Download a file or folder from the OpenMates server or from a cloud storage account.'>",
        "responses": {
            "200": {
                "description": "Successful Response",
                "content": {
                    "application/octet-stream": {
                        "schema": {
                            "type": "string",
                            "format": "binary"
                        },
                        "example": {
                            "summary": "Example file download",
                            "description": "This endpoint returns the requested file as a binary stream. The actual content cannot be displayed here.",
                            "value": "Binary file content"
                        }
                    }
                }
            },
            **generate_responses([400, 401, 403, 404, 422, 500])
        }
    },
    "delete": {
        "response_model": FilesDeleteOutput,
        "summary": "Skill | Delete",
        "description": "<img src='images/apps/files/delete.png' alt='Delete a file or folder from the OpenMates server or from a cloud storage account.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

# Finance
apps_finance_endpoints = {
    "get_report":{
        "response_model":FinanceGetReportOutput,
        "summary": "Skill | Get report",
        "description": "<img src='images/apps/finance/get_report.png' alt='Get a report about your transactions. You can choose from various kinds of reports.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    "get_transactions":{
        "response_model":FinanceGetTransactionsOutput,
        "summary": "Skill | Get Transactions",
        "description": "<img src='images/apps/finance/get_transactions.png' alt='Get all or specific bank transactions from any of your bank accounts in your accounting software.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

# Health
apps_health_endpoints = {
    # /v1/{team_slug}/apps/health/search_doctors
    "search_doctors":{
        "response_model":HealthSearchDoctorsOutput,
        "summary": "Skill | Search doctors",
        "description": "<img src='images/apps/health/search_doctors.png' alt='Searches for doctors based on your requirements.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    # /v1/{team_slug}/apps/health/search_appointments
    "search_appointments":{
        "response_model":HealthSearchAppointmentsOutput,
        "summary": "Skill | Search appointments",
        "description": "<img src='images/apps/health/search_appointments.png' alt='Searches for available appointments based on your requirements.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

# Home
apps_home_endpoints = {
    # /v1/{team_slug}/apps/home/get_all_devices
    "get_all_devices":{
        "response_model":HomeGetAllDevicesOutput,
        "summary": "Skill | Get all devices",
        "description": "<img src='images/apps/home/get_all_devices.png' alt='Get a list of all devices in your home. You can also filter for device categories or rooms.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    # /v1/{team_slug}/apps/home/get_all_scenes
    "get_all_scenes":{
        "response_model":HomeGetAllScenesOutput,
        "summary": "Skill | Get all scenes",
        "description": "<img src='images/apps/home/get_all_scenes.png' alt='Get a list of all scenes in your home.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    # /v1/{team_slug}/apps/home/add_device
    "add_device":{
        "response_model":HomeAddDeviceOutput,
        "summary": "Skill | Add device",
        "description": "<img src='images/apps/home/add_device.png' alt='Add a device to your smart home.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    # /v1/{team_slug}/apps/home/add_scene
    "add_scene":{
        "response_model":HomeAddSceneOutput,
        "summary": "Skill | Add scene",
        "description": "<img src='images/apps/home/add_scene.png' alt='Add a scene at your home. For example to turn on/off certain lights or devices.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    # /v1/{team_slug}/apps/home/set_scene
    "set_scene":{
        "response_model":HomeSetSceneOutput,
        "summary": "Skill | Set scene",
        "description": "<img src='images/apps/home/set_scene.png' alt='Set a scene at your home. For example to turn on/off certain lights or devices.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    # /v1/{team_slug}/apps/home/set_device
    "set_device":{
        "response_model":HomeSetDeviceOutput,
        "summary": "Skill | Set device",
        "description": "<img src='images/apps/home/set_device.png' alt='Turn a device on or off, change the brightness, color or effect of an LED lamp or set a certain temperature for your heating.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    # /v1/{team_slug}/apps/home/get_temperature
    "get_temperature":{
        "response_model":HomeGetTemperatureOutput,
        "summary": "Skill | Get temperature",
        "description": "<img src='images/apps/home/get_temperature.png' alt='Get the current temperature from a specific sensor, all sensors in a room or all sensors in your home.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    # /v1/{team_slug}/apps/home/get_power_consumption
    "get_power_consumption":{
        "response_model":HomeGetPowerConsumptionOutput,
        "summary": "Skill | Get power consumption",
        "description": "<img src='images/apps/home/get_power_consumption.png' alt='Get power consumption data from a device, for your room or your home.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

# Maps
apps_maps_endpoints = {
    # /v1/{team_slug}/apps/maps/search
    "search_places":{
        "response_model":MapsSearchOutput,
        "summary": "Skill | Search",
        "description": "<img src='images/apps/maps/search.png' alt='Search for places.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

# Messages
apps_messages_endpoints = {
    # /v1/{team_slug}/apps/messages/send
    "send":{
        "response_model":MessagesSendOutput,
        "summary": "Skill | Send",
        "description": "<img src='images/apps/messages/send.png' alt='Send a new message to a channel or thread.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    # /v1/{team_slug}/apps/messages/connect
    "connect":{
        "response_model":MessagesConnectOutput,
        "summary": "Skill | Connect",
        "description": "<img src='images/apps/messages/connect.png' alt='Connect a third party messenger. Allows you to chat with your AI team mates in that messenger.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

# PDF Editor
apps_pdf_editor_endpoints = {
}

# Photos
apps_photos_endpoints = {
     "resize_image":{
        "summary": "Skill | Resize",
        "description": "<img src='images/apps/photos/resize.png' alt='Scale or crop an existing image to a higher or lower resolution. Can also use AI upscaling for even better results.'>",
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

# Travel
apps_travel_endpoints = {
    # /v1/{team_slug}/apps/travel/search_connections
    "search_connections":{
        "response_model":TravelSearchConnectionsOutput,
        "summary": "Skill | Search connections",
        "description": "<img src='images/apps/travel/search_connections.png' alt='Search for the best connections via train, plane and bus. Also considers events like extreme weather and other unexpected events.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

# Videos
apps_videos_endpoints = {
    # /v1/{team_slug}/apps/videos/transcript
    "get_transcript":{
        "response_model":VideosGetTranscriptOutput,
        "summary": "Skill | Get transcript",
        "description": "<img src='images/apps/videos/transcript.png' alt='Get the full transcript of a video.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}

# Web
apps_web_endpoints = {
    # /v1/{team_slug}/apps/web/read
    "read":{
        "response_model":WebReadOutput,
        "summary": "Skill | Read",
        "description": "<img src='images/apps/web/read.png' alt='Return the content of a website as easy to read text plus images. Great for news articles and blogs.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    },
    # /v1/{team_slug}/apps/web/view
    "view":{
        "response_model":WebViewOutput,
        "summary": "Skill | View",
        "description": "<img src='images/apps/web/view.png' alt='Return a website in its full form, including content that loads with scripts. Great for more complex websites.'>",
        "responses": generate_responses([200, 400, 401, 403, 404, 422, 500])
    }
}



tags_metadata = [
    {
        "name": "Mates",
        "description": "<img src='images/mates.png' alt='Mates are your AI team members. They can help you with various tasks. Each mate is specialized in a different area.'>"
    },
    {
        "name": "Teams",
        "description": "<img src='images/teams.png' alt='Manage the teams on your OpenMates server.'>"
    },
    {
        "name": "Users",
        "description": "<img src='images/users.png' alt='Manage user accounts of a team. A user can get personalized responses from mates and access to the OpenMates API.'>"
    },
    {
        "name": "Skills",
        "description": "<img src='images/skills.png' alt='Your team mate can use a wide range of app skills. Or, you can call them directly via the API.'>"
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
        "name": "Apps",
        "description": "<img src='images/apps.png' alt='Your team mates can interact with a wide range of apps, on your behalf. For example: ChatGPT, Notion, RSS, SevDesk, YouTube, Claude, StableDiffusion, Firefox, Dropbox.'>"
    },
    {
        "name": "Apps | AI",
        "description": "<img src='images/apps/ai.png' alt='Use generative AI to answer questions, brainstorm ideas, create images and more. \
            Providers: Claude, ChatGPT\
            Models: claude-3.5-sonnet, claude-3-haiku, gpt-4o, gpt-4o-mini'>"
    },
    {
        "name": "Apps | Audio",
        "description": "<img src='images/apps/audio.png' alt='Generate, modify and transcribe audio and more. Providers: OpenAI, AssemblyAI, ElevenLabs'>"
    },
    {
        "name": "Apps | Books",
        "description": "<img src='images/apps/books.png' alt='Manage your ebooks, translate them and more. Providers: Amazon Kindle'>"
    },
    {
        "name": "Apps | Docs",
        "description": "<img src='images/apps/docs.png' alt='Create documents for everything from contracts to CVs and more. Providers: Google Docs, Microsoft Word, OnlyOffice'>"
    },
    {
        "name": "Apps | Files",
        "description": "<img src='images/apps/files.png' alt='Manage your files, regardless of where they are. Providers: OpenMates, Dropbox'>"
    },
    {
        "name": "Apps | Finance",
        "description": "<img src='images/apps/finance.png' alt='Keep track of your finances and build a stable income. Providers: Akaunting, Revolut Business'>"
    },
    {
        "name": "Apps | Health",
        "description": "<img src='images/apps/health.png' alt='Everything to improve your health and well being. Providers: Doctolib'>"
    },
    {
        "name": "Apps | Home",
        "description": "<img src='images/apps/home.png' alt='Control your smart home, organize daily tasks and more. Providers: Home Assistant, Tasmota'>"
    },
    {
        "name": "Apps | Maps",
        "description": "<img src='images/apps/maps.png' alt='Find restaurants, bars and so much more - nearby and around the world. Providers: Google Maps'>"
    },
    {
        "name": "Apps | Messages",
        "description": "<img src='images/apps/messages.png' alt='Send messages, create threads and more. \
            Providers: Discord, Slack, Mattermost'>"
    },
    {
        "name": "Apps | Photos",
        "description": "<img src='images/apps/photos.png' alt='Modify images, resize them and more.'>"
    },
    {
        "name": "Apps | Travel",
        "description": "<img src='images/apps/travel.png' alt='Plan your next trip with ease. Providers: Google Maps'>"
    },
    {
        "name": "Apps | Videos",
        "description": "<img src='images/apps/videos.png' alt='Search for videos, get their transcript and more. Providers: YouTube'>"
    },
    {
        "name": "Apps | Web",
        "description": "<img src='images/apps/web.png' alt='Browse the web, researches topics and more.'>"
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
    "app_slug": {
        "description": "The slug of the software",
        "examples": ["claude"]
    },
    "skill_slug": {
        "description": "The slug of the skill",
        "examples": ["ask"]
    },
    "provider": {
        "description": "The name of the service provider",
        "examples": ["dropbox"]
    },
    "file_path": {
        "description": "The path to the file",
        "examples": ["documents/contract.pdf"]
    },
}

