
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

from server.api.models.mates import Mate, MatesAskInput, MatesAskOutput, MatesGetAllOutput, mates_get_all_output_example


def generate_responses(status_codes):
    descriptions = {
        "200": "Successful Response",
        "422": "Validation Error",
        "401": "Unauthorized",
        "404": "Not Found",
        "500": "Internal Server Error"
    }
    
    responses = {}
    for code in status_codes:
        responses[str(code)] = {"description": descriptions.get(str(code), "Unknown Status Code"), "model": None}
    
    return responses


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

endpoint_metadata = {
    "get_all_mates":{
        "response_model":MatesGetAllOutput,
        "summary": "Get all",
        "description": "<img src='images/mates/get_all.png' alt='Get an overview list of all AI team mates currently active on the OpenMates server.'>",
        "responses": generate_responses([200, 401, 404, 422, 500]),
    },
    "get_mate":{
        "response_model":Mate,
        "summary": "Get mate",
        "description": "<img src='images/mates/get_mate.png' alt='Get all details about a specific mate. Including system prompt, available skills and more.'>",
        "responses": generate_responses([200, 401, 404, 422, 500])
    }
    
}

input_parameter_descriptions = {
    "team_url": {
        "description": "The URL of the team",
        "example": "openmates_enthusiasts"
    },
    "token": {
        "description": "The authentication token",
        "example": "123456789"
    },
    "mate_username":{
        "description": "The username of the AI team mate",
        "example": "sophia"
    }
}

